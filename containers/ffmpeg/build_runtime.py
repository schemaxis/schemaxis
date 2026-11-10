"""Rebuild the reviewed FFmpeg/x264 subset with a relocatable public prefix.

Run under an independently enforced memory/no-swap/deadline envelope. This
script limits make to two jobs; it does not claim to establish a kernel limit.
Sources remain read-only. Only the requested build/install/log directories and
home transcript are written. The image bundle needs ffmpeg and ffprobe, licence
texts and the corresponding source/build provenance, not the source trees.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tarfile
import time

FFMPEG_SHA256 = '8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e'
X264_COMMIT = 'b35605ace3ddf7c1a5d67a2eb553f034aef41d55'
PREFIX = '/opt/runtime'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_sources(archive_path, source, x264):
    if sha(archive_path) != FFMPEG_SHA256:
        raise ValueError('FFmpeg archive does not match the reviewed release')
    expected = set()
    with tarfile.open(archive_path) as archive:
        for member in archive:
            relative = Path(member.name)
            if (relative.is_absolute() or '..' in relative.parts
                    or not relative.parts or relative.parts[0] != 'ffmpeg-9.0.2'):
                raise ValueError('Unsafe FFmpeg source member')
            relative = Path(*relative.parts[1:])
            target = source/relative
            if member.isfile():
                expected.add(relative.as_posix())
                if target.is_symlink() or not target.is_file():
                    raise ValueError('FFmpeg source file is missing or linked')
                original = archive.extractfile(member)
                if hashlib.file_digest(original, 'sha256').hexdigest() != sha(target):
                    raise ValueError('FFmpeg source differs from the retained release')
            elif member.issym():
                expected.add(relative.as_posix())
                if not target.is_symlink() or os.readlink(target) != member.linkname:
                    raise ValueError('FFmpeg source link differs')
            elif not member.isdir():
                raise ValueError('Unsupported FFmpeg source member')
    actual = {path.relative_to(source).as_posix() for path in source.rglob('*')
              if path.is_file() or path.is_symlink()}
    if actual != expected:
        raise ValueError('FFmpeg source contains unexpected files')
    commit = subprocess.check_output(['git', '-C', str(x264), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(x264), 'status', '--porcelain'], text=True).strip()
    if commit != X264_COMMIT or dirty:
        raise ValueError('x264 source is not the clean reviewed commit')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg-archive', type=Path, required=True)
    parser.add_argument('--ffmpeg-source', type=Path, required=True)
    parser.add_argument('--x264-source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--home-log', type=Path, required=True)
    args = parser.parse_args()
    source, x264, root = (path.resolve() for path in
                          (args.ffmpeg_source, args.x264_source, args.destination))
    if root.exists() or any(root == path or root.is_relative_to(path) for path in (source, x264)):
        raise ValueError('A fresh destination outside both source trees is required')
    check_sources(args.ffmpeg_archive, source, x264)
    root.mkdir(parents=True)
    build = root/'build'
    logs = root/'logs'
    install = root/'install'
    home = root/'home'
    for path in (build/'x264', build/'ffmpeg', build/'tmp', logs, home):
        path.mkdir(parents=True)
    environment = {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'LC_ALL': 'C',
        'TMPDIR': str(build/'tmp'),
        'CFLAGS': '-O2 '+ ' '.join('-ffile-prefix-map='+str(path)+'='+canonical
                                  for path, canonical in ((source, '/source/ffmpeg'),
                                      (x264, '/source/x264'), (root, '/build')))}
    stages = []

    def run(name, command, directory, extra=None):
        started = time.monotonic()
        # Out-of-tree configure scripts may compile relative source names.
        # Map those at compilation too, so __FILE__ never captures the build
        # layout. This changes compiler inputs, not the resulting binaries.
        relative_maps = ' '.join(
            '-ffile-prefix-map='+os.path.relpath(path, directory)+'='+canonical
            for path, canonical in ((root, '/build'), (source, '/source/ffmpeg'),
                                     (x264, '/source/x264')))
        stage_environment = {**environment,
            'CFLAGS': environment['CFLAGS']+' '+relative_maps, **(extra or {})}
        with (logs/(name+'.log')).open('wb') as output:
            process = subprocess.Popen([str(value) for value in command], cwd=directory,
                env=stage_environment, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, start_new_session=True)
            tee = subprocess.Popen(['tee', '-a', str(args.home_log)], stdin=process.stdout, stdout=output)
            process.stdout.close()
            try:
                code = process.wait(timeout=180)
                tee_code = tee.wait(timeout=10)
            except BaseException:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
                tee.kill()
                tee.wait(timeout=5)
                raise
        stages.append({'stage': name, 'exitCode': code, 'teeExitCode': tee_code,
                       'wallSeconds': time.monotonic()-started})
        (root/'stages.json').write_text(json.dumps(stages, indent=2)+'\n')
        if code or tee_code:
            raise RuntimeError('Build stage failed: '+name)

    xflags = ['--prefix='+PREFIX, '--enable-static', '--disable-cli', '--disable-asm',
        '--enable-pic', '--bit-depth=8', '--disable-opencl', '--disable-avs',
        '--disable-swscale', '--disable-lavf', '--disable-ffms', '--disable-gpac', '--disable-lsmash']
    run('x264-configure', [x264/'configure', *xflags], build/'x264')
    run('x264-build', ['make', '-j2'], build/'x264')
    run('x264-install', ['make', 'DESTDIR='+str(install), 'install'], build/'x264')
    # pkg-config is build-only. Keep the installed public-prefix .pc unchanged;
    # this separate build-only copy resolves the DESTDIR without changing zlib.
    pkg = build/'pkgconfig'
    pkg.mkdir()
    pc = install/'opt/runtime/lib/pkgconfig/x264.pc'
    (pkg/'x264.pc').write_text(pc.read_text().replace('prefix='+PREFIX, 'prefix='+str(install/'opt/runtime')))
    flags = ['--prefix='+PREFIX, '--pkg-config=pkg-config', '--pkg-config-flags=--static',
        '--disable-everything', '--disable-autodetect', '--disable-network', '--disable-doc',
        '--disable-debug', '--disable-asm', '--disable-shared', '--enable-static', '--disable-ffplay',
        '--enable-ffmpeg', '--enable-ffprobe', '--enable-gpl', '--enable-libx264', '--enable-zlib',
        '--enable-protocol=file,pipe',
        '--enable-demuxer=rawvideo,matroska,mov,avi,wav,srt,webvtt,image2,h264,aac',
        '--enable-muxer=matroska,mp4,mov,avi,wav,srt,webvtt,rawvideo,image2,null',
        '--enable-decoder=ffv1,h264,rawvideo,png,pcm_s16le,aac,movtext,srt,subrip,webvtt',
        '--enable-encoder=libx264,ffv1,rawvideo,png,pcm_s16le,aac,movtext,srt,subrip,webvtt',
        '--enable-parser=h264,aac,png',
        '--enable-bsf=aac_adtstoasc,h264_mp4toannexb,extract_extradata,null,setts',
        '--enable-filter=scale,format,fps,setsar,setpts,trim,aresample,anull,aformat,null,atrim,asetpts',
        '--enable-swscale', '--enable-swresample', '--cc=cc', '--extra-cflags=-O2']
    extra = {'PKG_CONFIG_PATH': str(pkg)}
    run('ffmpeg-configure', [source/'configure', *flags], build/'ffmpeg', extra)
    run('ffmpeg-build', ['make', '-j2'], build/'ffmpeg', extra)
    run('ffmpeg-install', ['make', 'DESTDIR='+str(install), 'install'], build/'ffmpeg', extra)
    records = {}
    for name in ('ffmpeg', 'ffprobe'):
        path = install/'opt/runtime/bin'/name
        data = path.read_bytes()
        if any(str(private).encode() in data for private in (Path.home(), source, x264, root)):
            raise RuntimeError('Compiled runtime retains a private source/build path')
        records[name] = {'sha256': sha(path), 'bytes': path.stat().st_size}
    provenance = {'ffmpegVersion': '9.0.2', 'ffmpegArchiveSha256': FFMPEG_SHA256,
        'x264Commit': X264_COMMIT, 'prefix': PREFIX, 'x264Configure': xflags,
        'ffmpegConfigure': flags, 'sourcePathsMapped': True, 'maxBuildJobs': 2,
        'recipeSha256': sha(__file__), 'binaries': records,
        'toolchain': {name: sha(Path('/usr/bin')/name) for name in ('cc', 'make', 'pkg-config')},
        'compilerVersion': subprocess.check_output(['/usr/bin/cc', '--version'], text=True, timeout=5).splitlines()[0],
        'scope': 'runtime rebuild only; image/native qualification remains separate'}
    (root/'provenance.json').write_text(json.dumps(provenance, indent=2)+'\n')
    print(json.dumps(provenance, indent=2))


if __name__ == '__main__':
    main()
