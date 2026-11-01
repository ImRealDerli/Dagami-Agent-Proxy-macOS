import fcntl,os,signal,sys,termios


def main():
    if len(sys.argv)<2:return 2
    fcntl.ioctl(0,termios.TIOCSCTTY,0)
    signal.signal(signal.SIGTTOU,signal.SIG_IGN)
    os.tcsetpgrp(0,os.getpgrp())
    signal.signal(signal.SIGTTOU,signal.SIG_DFL)
    os.execvpe(sys.argv[1],sys.argv[1:],os.environ)

if __name__=='__main__':raise SystemExit(main())
