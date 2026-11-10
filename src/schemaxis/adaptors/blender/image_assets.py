"""Bounded captured single-image resources, without native imports."""
import hashlib
import os
import stat
import struct
import zlib
from contextlib import contextmanager
from schemaxis.errors import fail

MAX_FILE_BYTES=64*1024*1024
MAX_CAPTURE_BYTES=256*1024*1024
MAX_PIXELS=4*1024*1024
MAX_TOTAL_PIXELS=16*1024*1024
MAX_DIMENSION=8192
ALPHA={'straight':'STRAIGHT','premultiplied':'PREMUL','channelPacked':'CHANNEL_PACKED','ignore':'NONE'}


@contextmanager
def source_stream(path,where):
    """Open only regular image files, without blocking on a FIFO replacement."""
    descriptor=None
    try:
        descriptor=os.open(path,os.O_RDONLY|os.O_NONBLOCK)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            fail('INVALID_RESOURCE','image input must be a regular file',where)
        stream=os.fdopen(descriptor,'rb');descriptor=None
        with stream:yield stream
    except FileNotFoundError:
        fail('RESOURCE_NOT_FOUND','image input is absent; restore it or correct its path',where)
    except (IsADirectoryError,NotADirectoryError):
        fail('INVALID_RESOURCE','image input must be a regular file',where)
    except OSError:
        fail('RESOURCE_UNREADABLE','image input cannot be read; check its permissions and storage',where)
    finally:
        if descriptor is not None:os.close(descriptor)


def digest_file(path,where):
    value=hashlib.sha256();count=0
    with source_stream(path,where) as stream:
        while data:=stream.read(min(1024*1024,MAX_FILE_BYTES-count+1)):
            count+=len(data)
            if count>MAX_FILE_BYTES:fail('RESOURCE_BUDGET_EXCEEDED','captured image exceeds 64 MiB',where)
            value.update(data)
    return value.hexdigest()


def capture_file(source,target,expected,where):
    if type(expected) is not int or not 0<=expected<=MAX_FILE_BYTES:
        fail('RESOURCE_BUDGET_EXCEEDED','image capture requires a bounded byte count',where)
    value=hashlib.sha256();count=0
    try:
        with source_stream(source,where) as stream,target.open('wb') as output:
            while data:=stream.read(min(1024*1024,expected-count+1)):
                count+=len(data)
                if count>expected or count>MAX_FILE_BYTES:fail('INPUT_CHANGED','image grew during bounded capture',where)
                value.update(data);output.write(data)
        if count!=expected or digest_file(source,where)!=value.hexdigest():
            fail('INPUT_CHANGED','image changed during bounded capture',where)
        return value.hexdigest()
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def dimensions(width,height,where):
    if width<=0 or height<=0:fail('INVALID_IMAGE','image dimensions must be positive',where)
    if max(width,height)>MAX_DIMENSION or width*height>MAX_PIXELS:
        fail('RESOURCE_BUDGET_EXCEEDED','image exceeds 8192 per axis or 4194304 pixels',where)
    return width*height


def admit_file(path,where,total=0):
    # Common PNG/JPEG dimensions are admitted before native pixel decoding.
    # Other native image formats receive the same pixel budget immediately
    # after loading, before packing or material evaluation.
    with source_stream(path,where) as stream:
        size=os.fstat(stream.fileno()).st_size
        if size>MAX_FILE_BYTES or total+size>MAX_CAPTURE_BYTES:
            fail('RESOURCE_BUDGET_EXCEEDED','captured images exceed 64 MiB per file or 256 MiB aggregate',where)
        header=stream.read(33)
        if header.startswith(b'\x89PNG\r\n\x1a\n'):
            if (len(header)!=33 or header[8:16]!=b'\0\0\0\rIHDR'
                    or zlib.crc32(header[12:29])&0xffffffff!=struct.unpack('>I',header[29:33])[0]):
                fail('INVALID_IMAGE','invalid PNG dimension header',where)
            dimensions(*struct.unpack('>II',header[16:24]),where)
        elif header.startswith(b'\xff\xd8'):
            stream.seek(2)
            for _ in range(65536):
                if stream.read(1)!=b'\xff':break
                marker=stream.read(1)
                while marker==b'\xff':marker=stream.read(1)
                if not marker:break
                kind=marker[0]
                if kind in (0xd9,0xda):break
                if kind in (0xd8,0x01) or 0xd0<=kind<=0xd7:continue
                raw=stream.read(2)
                if len(raw)!=2:break
                length=struct.unpack('>H',raw)[0]
                if length<2:break
                if kind in (0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf):
                    data=stream.read(5)
                    if length<8 or len(data)!=5:break
                    height,width=struct.unpack('>HH',data[1:]);dimensions(width,height,where)
                    return total+size
                stream.seek(length-2,1)
            fail('INVALID_IMAGE','JPEG has no bounded valid dimension header',where)
    return total+size
