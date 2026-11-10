"""Regenerate the third-party-style HDF5 adoption fixture with plain h5py (not the Schemaxis adaptor).

Run with the isolated HDF5 runtime:  PYTHON -I tools/hdf5_fixtures.py examples/schemaxis/hdf5-fixtures
The file imitates an instrument vendor's export: superblock 0 (libver earliest), nested groups,
fixed-length ASCII attributes, a gzip chunked 2-D frame stack with a time scale, a compound log and
a soft link. Its literal contents are the reviewed expectations used by the conformance cases.
"""
import sys

import h5py
import numpy as np


def main(directory):
    with h5py.File(directory + '/vendor-export.h5', 'w', libver='earliest') as f:
        f.attrs.create('vendor', np.bytes_('ACME Optics'), dtype='S11')
        f.attrs['format_version'] = np.int32(3)
        acq = f.create_group('acquisition')
        acq.attrs['operator'] = 'R. Ng'
        t = acq.create_dataset('time', data=np.array([0.0, 0.25, 0.5, 0.75]), track_times=False)
        t.attrs['units'] = 'ms'
        t.make_scale('time')
        frames = acq.create_dataset('frames', data=(np.arange(24, dtype='<u2').reshape(4, 2, 3) * 10),
                                    chunks=(1, 2, 3), compression='gzip', compression_opts=1, track_times=False)
        frames.attrs['units'] = 'counts'
        frames.dims[0].attach_scale(t)
        frames.dims[0].label = 'time'
        log = np.array([(0, b'START'), (3, b'STOP')], dtype=[('frame', '<i4'), ('event', 'S8')])
        acq.create_dataset('log', data=log, track_times=False)
        f['latest_frames'] = h5py.SoftLink('/acquisition/frames')


if __name__ == '__main__':
    main(sys.argv[1])
