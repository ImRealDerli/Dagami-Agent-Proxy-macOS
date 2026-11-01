import struct,unittest
from devproxy_pkg.macos_backend import cli_gate,patch_data,PATTERNS

def fixture(arch=0x01000007,duplicate=False):
    header=struct.pack('<8I',0xfeedfacf,arch,3,2,1,152,0,0)
    command=bytearray(152);struct.pack_into('<II',command,0,0x19,152);command[8:14]=b'__TEXT';struct.pack_into('<I',command,64,1)
    at=72;command[at:at+6]=b'__text';command[at+16:at+22]=b'__TEXT'
    start=256;code=bytearray(256)
    pos=16;signature=b'\x48\x85\xc0\x0f\x84'+struct.pack('<i',100-9)+b'\x80\x78\x08\x00\x0f\x85'+struct.pack('<i',100-19)+b'\x48\x8b\x50\x50\x4c\x8d\x1d'
    code[pos:pos+len(signature)]=signature
    if duplicate:code[128:128+len(signature)]=signature
    struct.pack_into('<Q',command,at+40,len(code));struct.pack_into('<I',command,at+48,start);struct.pack_into('<I',command,at+64,0x80000400)
    return header+command+b'\0'*(start-len(header)-len(command))+code+b'prompt-interactive\0Eligibility check failed:\0Go build ID:\0'+b'\0'.join(PATTERNS)+b'\0https_proxy\0'

class CliPatchTests(unittest.TestCase):
    def test_patch_only_validated_branch_and_all_eight_metadata_fields(self):
        original=fixture();offset=cli_gate(original);patched=patch_data(original,cli=True)
        self.assertEqual(len(original),len(patched));self.assertEqual(b'\x48\x85\xc0\x90',patched[offset:offset+4])
        self.assertEqual(original[:offset],patched[:offset]);self.assertIn(b'AG_LS_PROXY',patched)
        for p in PATTERNS:self.assertIn(p.replace(b'ineligible',b'dpeligible'),patched)
    def test_unsupported_arch_duplicate_truncation_and_partial_patch_rejected(self):
        for value in (fixture(arch=0x0100000c),fixture(duplicate=True),fixture()[:100],fixture().replace(PATTERNS[0],b'unsupported'),patch_data(fixture(),cli=True)):
            with self.assertRaises(ValueError):patch_data(value,cli=True)
    def test_branch_outside_executable_section_is_not_accepted(self):
        data=bytearray(fixture());struct.pack_into('<Q',data,32+72+40,1)
        with self.assertRaises(ValueError):cli_gate(data)
