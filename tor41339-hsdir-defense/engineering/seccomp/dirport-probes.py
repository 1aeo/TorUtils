"""Single, ordinary/malformed HTTP requests to one lab relay's DirPort on
127.0.0.1, to drive the 0003/0004/0005 parser paths under the seccomp sandbox.
No load: one request per probe."""
import socket, sys, time
port = int(sys.argv[1])
def probe(name, data, read=True):
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
    out = b""
    try:
        s.sendall(data)
        while read:
            b = s.recv(65536)
            if not b: break
            out += b
    except socket.timeout:
        out += b"<timeout>"
    except OSError as e:
        out += f"<{type(e).__name__}>".encode()
    s.close()
    print(f"[{name}] sent={len(data)} got={len(out)} first_line={out.split(b'\r\n',1)[0][:80]!r}")
# 0004: declared Content-Length above HSV3MaxDescriptorSize -> rejected before body arrives
probe("post-oversized-declared", b"POST /tor/hs/3/publish HTTP/1.0\r\nContent-Length: 60000\r\n\r\n")
# 0004: actual oversized body
probe("post-oversized-actual", b"POST /tor/hs/3/publish HTTP/1.0\r\nContent-Length: 60000\r\n\r\n" + b"A"*60000)
# 0005: GET followed by trailing bytes in the same write
probe("get-with-trailing", b"GET /tor/server/authority HTTP/1.0\r\n\r\nTRAILING-GARBAGE"*1)
# 0003: malformed headers / bogus Content-Length
probe("bogus-content-length", b"POST /tor/hs/3/publish HTTP/1.0\r\nContent-Length: -5\r\n\r\n")
probe("oversized-headers", b"GET /" + b"a"*70000 + b" HTTP/1.0\r\n\r\n")
# ordinary GET of an HS descriptor over the DirPort (non-anonymous -> refused by stock rule)
probe("get-hs-desc-dirport", b"GET /tor/hs/3/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA HTTP/1.0\r\n\r\n")
