"""Portable SHA-256 continuation for a frozen, public legacy fingerprint prefix.

Only a chaining state, byte length and partial block are retained; no historical
algorithm source is shipped. Used exclusively for the verified legacy revision.
"""
import struct

_K = (
 0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
 0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
 0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
 0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
 0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
 0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
 0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
 0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2)
_MASK = 0xffffffff

def _ror(n, bits):
    return ((n >> bits) | (n << (32-bits))) & _MASK


class SHA256:
    def __init__(self, checkpoint=None):
        checkpoint = checkpoint or dict(state=[0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19], length=0, pending='')
        self.state = list(checkpoint['state'])
        self.length = checkpoint['length']
        self.pending = bytes.fromhex(checkpoint['pending'])
        if self.length % 64 != len(self.pending):
            raise ValueError('Invalid SHA-256 checkpoint')

    def update(self, value):
        self.length += len(value)
        value = self.pending + value
        complete = len(value) // 64 * 64
        for offset in range(0, complete, 64):
            w = list(struct.unpack('>16I', value[offset:offset+64]))
            for i in range(16,64):
                x,y = w[i-15],w[i-2]
                w.append((w[i-16]+(_ror(x,7)^_ror(x,18)^(x>>3))+w[i-7]+(_ror(y,17)^_ror(y,19)^(y>>10)))&_MASK)
            a,b,c,d,e,f,g,h = self.state
            for k,x in zip(_K,w):
                t1 = (h+(_ror(e,6)^_ror(e,11)^_ror(e,25))+((e&f)^((~e)&g))+k+x)&_MASK
                t2 = ((_ror(a,2)^_ror(a,13)^_ror(a,22))+((a&b)^(a&c)^(b&c)))&_MASK
                a,b,c,d,e,f,g,h = (t1+t2)&_MASK,a,b,c,(d+t1)&_MASK,e,f,g
            self.state = [(x+y)&_MASK for x,y in zip(self.state,(a,b,c,d,e,f,g,h))]
        self.pending = value[complete:]
        return self

    def checkpoint(self):
        return dict(state=self.state, length=self.length, pending=self.pending.hex())

    def hexdigest(self):
        copy = SHA256(self.checkpoint())
        copy.update(b'\x80'+b'\0'*((55-self.length)%64)+struct.pack('>Q',self.length*8))
        return ''.join(f'{x:08x}' for x in copy.state)


class NativeContinuation:
    """OpenSSL SHA256_CTX continuation on the Linux/systemd Viewer host.

    Layout follows the installed OpenSSL public openssl/sha.h. Keep the portable
    implementation above as a test/reference and checkpoint generator; runtime
    catalogs are streamed through OpenSSL, never through a Python compression loop.
    """
    def __init__(self, checkpoint):
        import ctypes as c
        class Context(c.Structure):
            _fields_ = [('h', c.c_uint32*8), ('Nl',c.c_uint32), ('Nh',c.c_uint32),
                        ('data',c.c_uint32*16), ('num',c.c_uint), ('md_len',c.c_uint)]
        self.c=c; self.Context=Context
        try:
            self.lib=c.CDLL('libcrypto.so.3')
            self.update_fn=self.lib.SHA256_Update
            self.final_fn=self.lib.SHA256_Final
        except (OSError,AttributeError) as error:
            raise RuntimeError('Growth legacy fingerprint compatibility requires OpenSSL 3 libcrypto') from error
        self.update_fn.argtypes=[c.POINTER(Context),c.c_void_p,c.c_size_t];self.update_fn.restype=c.c_int
        self.final_fn.argtypes=[c.c_void_p,c.POINTER(Context)];self.final_fn.restype=c.c_int
        pending=bytes.fromhex(checkpoint['pending']);length=checkpoint['length']
        if length % 64 != len(pending) or len(checkpoint['state'])!=8:raise ValueError('Invalid SHA-256 checkpoint')
        self.ctx=Context()
        self.ctx.h[:]=checkpoint['state'];self.ctx.Nl=(length*8)&_MASK;self.ctx.Nh=(length*8)>>32
        self.ctx.num=len(pending);self.ctx.md_len=32
        c.memmove(c.addressof(self.ctx)+Context.data.offset,pending,len(pending))

    def update(self, value):
        if self.update_fn(self.c.byref(self.ctx),value,len(value))!=1:raise RuntimeError('SHA256_Update failed')
        return self

    def hexdigest(self):
        copy=self.Context.from_buffer_copy(self.ctx)
        output=(self.c.c_ubyte*32)()
        if self.final_fn(output,self.c.byref(copy))!=1:raise RuntimeError('SHA256_Final failed')
        return bytes(output).hex()
