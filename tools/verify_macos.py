
import argparse
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def filtered(suite,headless):
    result=unittest.TestSuite()
    for test in suite:
        if isinstance(test,unittest.TestSuite):result.addTests(filtered(test,headless))
        elif not (headless and test.__class__.__name__ in ('DesktopTests','EditorGuiTests')):result.addTest(test)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--headless',action='store_true');args=parser.parse_args()
    from devproxy_pkg.core.secrets import MacOSKeychainStore
    cache={}
    with tempfile.TemporaryDirectory(prefix='dagami-checks-') as temp,patch.dict(os.environ,{'DEVPROXY_HOME':temp}),patch.object(MacOSKeychainStore,'set_password',side_effect=lambda k,u,v:cache.__setitem__(k,v) is None),patch.object(MacOSKeychainStore,'get_password',side_effect=lambda k:cache.get(k)),patch.object(MacOSKeychainStore,'delete_password',side_effect=lambda k:cache.pop(k,None) is not None):
        suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_*.py')
        result=unittest.TextTestRunner(verbosity=2).run(filtered(suite,args.headless))
        print('Keychain writes: mocked. Test data: temporary fixtures. Live accounts/system DNS: untouched.')
        return int(not result.wasSuccessful())

if __name__=='__main__':raise SystemExit(main())
