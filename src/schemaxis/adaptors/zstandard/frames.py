"""Independent Zstandard frame structure and decoded-content checksum inspection.

Format basis: Zstandard v1.5.7 doc/zstd_compression_format.md. Entropy-coded
blocks are decoded by the configured native application, not this host reader.
"""
import struct
from schemaxis.errors import fail
from schemaxis.dispatch import remaining_timeout

MASK=(1<<64)-1
P1,P2,P3,P4,P5=11400714785074694791,14029467366897019727,1609587929392839161,9650029242287828579,2870177450012600261
MAX_WINDOW=256*1024*1024


def _rotate(value,count):
    return ((value<<count)|(value>>(64-count)))&MASK


def _round(acc,value):
    return (_rotate((acc+value*P2)&MASK,31)*P1)&MASK


def xxh64(data):
    """Original implementation of the published XXH64 arithmetic, seed zero."""
    size=len(data);at=0
    if size>=32:
        values=[(P1+P2)&MASK,P2,0,(-P1)&MASK]
        while at<=size-32:
            if not at%32768:remaining_timeout()
            for index in range(4):values[index]=_round(values[index],int.from_bytes(data[at+8*index:at+8*index+8],'little'))
            at+=32
        result=sum(_rotate(value,count) for value,count in zip(values,(1,7,12,18)))&MASK
        for value in values:result=((result^_round(0,value))*P1+P4)&MASK
    else:result=P5
    result=(result+size)&MASK
    while at<=size-8:
        result=(_rotate(result^_round(0,int.from_bytes(data[at:at+8],'little')),27)*P1+P4)&MASK;at+=8
    if at<=size-4:
        result=(_rotate(result^(int.from_bytes(data[at:at+4],'little')*P1&MASK),23)*P2+P3)&MASK;at+=4
    while at<size:
        result=_rotate(result^(data[at]*P5&MASK),11)*P1&MASK;at+=1
    result^=result>>33;result=result*P2&MASK;result^=result>>29;result=result*P3&MASK;result^=result>>32
    return result


def inspect(data,*,max_decoded=64*1024*1024):
    """Read complete frame boundaries, declared sizes, windows, dictionaries and checksums."""
    at=0;frames=[];known=0;total_blocks=0
    def take(count):
        nonlocal at
        if count<0 or at+count>len(data):fail('INVALID_ZSTANDARD_FRAME','Truncated Zstandard frame',str(at))
        result=data[at:at+count];at+=count;return result
    while at<len(data):
        remaining_timeout()
        start=at;magic=int.from_bytes(take(4),'little')
        if 0x184d2a50<=magic<=0x184d2a5f:
            size=int.from_bytes(take(4),'little');take(size)
            frames.append({'kind':'skippable','offset':start,'bytes':at-start,'payloadBytes':size,'id':magic&15})
            if len(frames)>4096:fail('ZSTANDARD_BUDGET','Too many frames')
            continue
        if magic!=0xfd2fb528:fail('INVALID_ZSTANDARD_FRAME','Expected a Zstandard or skippable frame',str(start))
        descriptor=take(1)[0]
        if descriptor&8:fail('INVALID_ZSTANDARD_FRAME','Reserved frame-header bit is set',str(start))
        single=bool(descriptor&32);checksum=bool(descriptor&4);flag=descriptor>>6
        window=None
        if not single:
            value=take(1)[0];base=1<<(10+(value>>3));window=base+(base>>3)*(value&7)
        dictionary=int.from_bytes(take((0,1,2,4)[descriptor&3]),'little')
        count=(1 if single else 0,2,4,8)[flag]
        content=int.from_bytes(take(count),'little') if count else None
        if flag==1:content+=256
        if single:window=content
        if window is None or window>MAX_WINDOW:fail('ZSTANDARD_BUDGET','Frame window exceeds 256 MiB',str(start))
        if content is not None:
            known+=content
            if known>max_decoded:fail('ZSTANDARD_BUDGET','Declared decoded content exceeds the output budget',str(start))
        blocks=[]
        while True:
            value=int.from_bytes(take(3),'little');last=bool(value&1);kind=(value>>1)&3;size=value>>3
            if kind==3 or size>min(128*1024,window):fail('INVALID_ZSTANDARD_FRAME','Invalid block type or size',str(at-3))
            payload=1 if kind==1 else size;take(payload)
            blocks.append({'kind':('raw','rle','compressed')[kind],'size':size,'last':last})
            total_blocks+=1
            if not total_blocks%256:remaining_timeout()
            if total_blocks>131072:fail('ZSTANDARD_BUDGET','Too many frame blocks',str(start))
            if last:break
        check=int.from_bytes(take(4),'little') if checksum else None
        frames.append({'kind':'zstandard','offset':start,'bytes':at-start,'contentBytes':content,'windowBytes':window,
                       'dictionaryID':dictionary,'checksum':check,'singleSegment':single,'blocks':blocks})
        if len(frames)>4096:fail('ZSTANDARD_BUDGET','Too many frames')
    if not frames:fail('INVALID_ZSTANDARD_FRAME','At least one complete frame is required')
    return frames


def check_content(frame,decoded):
    if frame['contentBytes'] is not None and frame['contentBytes']!=len(decoded):
        fail('VERIFICATION_FAILED','Decoded length differs from the independent frame header')
    if frame['checksum'] is not None and frame['checksum']!=(xxh64(decoded)&0xffffffff):
        fail('VERIFICATION_FAILED','Decoded content differs from the independent XXH64 frame checksum')


def dictionary_id(data):
    if len(data)<8 or data[:4]!=b'\x37\xa4\x30\xec':
        fail('INVALID_ZSTANDARD_DICTIONARY','Expected a trained Zstandard dictionary')
    return struct.unpack_from('<I',data,4)[0]
