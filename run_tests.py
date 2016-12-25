#!/usr/bin/env python
import sys
import pytest
import os

if __name__ == '__main__':
    # show output results from every test function
    args = ['-v', '-vx', '-x']
    # show the message output for skipped and expected failure tests
    if len(sys.argv) > 1:
        args.extend(sys.argv[1:])
    print('pytest arguments: {}'.format(args))
    # # compute coverage stats for xpdAcq
    # args.extend(['--cov', 'xpdAcq'])
    # call pytest and exit with the return code from pytest so that
    # travis will fail correctly if tests fail
    os.environ['XPDAN_SETUP'] = 'test'
    exit_res = pytest.main(args)
    os.environ['XPDAN_SETUP'] = 'prod'
    sys.exit(exit_res)
