use serde::Deserialize;
use std::{
    fs, io,
    os::unix::fs::{MetadataExt, PermissionsExt},
    path::PathBuf,
    sync::Arc,
    time::Duration,
};
use std::{
    pin::Pin,
    task::{Context, Poll},
};
use tokio::io::{AsyncWrite, ReadBuf};
use tokio::{
    io::{AsyncRead, AsyncReadExt, AsyncWriteExt},
    net::{lookup_host, TcpStream, UnixListener, UnixStream},
    sync::Semaphore,
    task::JoinSet,
    time::{sleep, timeout, Instant},
};
use tokio_rustls::{
    rustls::{self, pki_types::ServerName},
    TlsConnector,
};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    socket: PathBuf,
    ca_file: Option<PathBuf>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    host: String,
    port: u16,
    tls: bool,
    timeout_ms: u64,
    #[serde(default)]
    fragment: u8,
}

async fn frame<R: AsyncRead + Unpin>(reader: &mut R) -> io::Result<Vec<u8>> {
    let mut data = Vec::new();
    for _ in 0..8192 {
        let byte = reader.read_u8().await?;
        if byte == b'\n' {
            return Ok(data);
        }
        data.push(byte);
    }
    Err(io::Error::new(
        io::ErrorKind::InvalidData,
        "control_frame_too_large",
    ))
}

async fn dial(host: &str, port: u16) -> io::Result<TcpStream> {
    let addresses = lookup_host((host, port)).await?.collect::<Vec<_>>();
    let (v6, v4): (Vec<_>, Vec<_>) = addresses.into_iter().partition(|v| v.is_ipv6());
    let mut ordered = Vec::new();
    let first_v6 = !v6.is_empty();
    for i in 0..v6.len().max(v4.len()) {
        let lists = if first_v6 { [&v6, &v4] } else { [&v4, &v6] };
        for list in lists {
            if let Some(address) = list.get(i) {
                if !ordered.contains(address) {
                    ordered.push(*address);
                }
            }
        }
    }
    if ordered.is_empty() {
        return Err(io::Error::new(io::ErrorKind::NotFound, "dns_no_addresses"));
    }
    let mut tasks = JoinSet::new();
    let mut next = 0;
    let mut due = Instant::now();
    loop {
        if next < ordered.len() && tasks.len() < 3 && Instant::now() >= due {
            let address = ordered[next];
            next += 1;
            tasks.spawn(async move {
                timeout(Duration::from_secs(3), TcpStream::connect(address))
                    .await
                    .map_err(|_| io::Error::new(io::ErrorKind::TimedOut, "address_timeout"))?
            });
            due = Instant::now() + Duration::from_millis(200);
        }
        if tasks.is_empty() && next >= ordered.len() {
            return Err(io::Error::new(
                io::ErrorKind::ConnectionRefused,
                "tcp_unreachable",
            ));
        }
        tokio::select! {
            result=tasks.join_next(), if !tasks.is_empty() => {
                match result {
                    Some(Ok(Ok(stream)))=>{tasks.abort_all();stream.set_nodelay(true)?;
                        let keepalive=socket2::TcpKeepalive::new().with_time(Duration::from_secs(30)).with_interval(Duration::from_secs(10));
                        let _=socket2::SockRef::from(&stream).set_tcp_keepalive(&keepalive);return Ok(stream);},
                    _=>{due=Instant::now();}
                }
            }
            _=sleep(Duration::from_millis(20)), if next<ordered.len() && tasks.len()<3 => {}
        }
    }
}

async fn respond(peer: &mut UnixStream, message: &[u8]) -> io::Result<()> {
    peer.write_all(message).await
}

async fn connection(
    mut peer: UnixStream,
    connector: TlsConnector,
    _slot: tokio::sync::OwnedSemaphorePermit,
) -> io::Result<()> {
    if peer.peer_cred()?.uid() != unsafe { libc::geteuid() } {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "foreign_user",
        ));
    }
    let bytes = timeout(Duration::from_secs(3), frame(&mut peer))
        .await
        .map_err(|_| io::Error::new(io::ErrorKind::TimedOut, "request_timeout"))??;
    let request: Request = serde_json::from_slice(&bytes)
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "invalid_request"))?;
    if request.host.is_empty()
        || request.host.len() > 253
        || request.host.chars().any(|c| c.is_control())
        || request.port == 0
        || !(1..=15000).contains(&request.timeout_ms)
        || !matches!(request.fragment, 0 | 1 | 8 | 32)
    {
        respond(&mut peer, b"{\"ok\":false,\"error\":\"invalid_request\"}\n").await?;
        return Ok(());
    }
    let destination = timeout(Duration::from_millis(request.timeout_ms), async {
        let tcp = dial(&request.host, request.port)
            .await
            .map_err(|_| "tcp_connect_failed")?;
        let tcp = SplitWrite {
            inner: tcp,
            size: request.fragment as usize,
            budget: 4096,
        };
        if request.tls {
            let name =
                ServerName::try_from(request.host.clone()).map_err(|_| "invalid_server_name")?;
            let tls = connector
                .connect(name, tcp)
                .await
                .map_err(|_| "tls_verification_or_handshake_failed")?;
            Ok::<_, &str>(Either::Tls(TlsEof(tls)))
        } else {
            Ok(Either::Plain(tcp))
        }
    })
    .await;
    match destination {
        Ok(Ok(Either::Plain(mut remote))) => {
            respond(&mut peer, b"{\"ok\":true}\n").await?;
            if let Err(error) =
                tokio::io::copy_bidirectional_with_sizes(&mut peer, &mut remote, 65536, 65536).await
            {
                eprintln!("Dagami network relay: {}", error.kind());
            }
        }
        Ok(Ok(Either::Tls(mut remote))) => {
            respond(&mut peer, b"{\"ok\":true}\n").await?;
            if let Err(error) =
                tokio::io::copy_bidirectional_with_sizes(&mut peer, &mut remote, 65536, 65536).await
            {
                eprintln!("Dagami network relay: {}", error.kind());
            }
        }
        result => {
            let error = match result {
                Err(_) => "connect_timeout",
                Ok(Err(error)) => error,
                _ => unreachable!(),
            };
            let message = serde_json::json!({"ok":false,"error":error}).to_string() + "\n";
            respond(&mut peer, message.as_bytes()).await?;
        }
    }
    Ok(())
}

struct SplitWrite<T> {
    inner: T,
    size: usize,
    budget: usize,
}
impl<T: AsyncRead + Unpin> AsyncRead for SplitWrite<T> {
    fn poll_read(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buffer: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        Pin::new(&mut self.get_mut().inner).poll_read(cx, buffer)
    }
}
impl<T: AsyncWrite + Unpin> AsyncWrite for SplitWrite<T> {
    fn poll_write(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        bytes: &[u8],
    ) -> Poll<io::Result<usize>> {
        let this = self.get_mut();
        let count = if this.size > 0 && this.budget > 0 {
            bytes.len().min(this.size).min(this.budget)
        } else {
            bytes.len()
        };
        match Pin::new(&mut this.inner).poll_write(cx, &bytes[..count]) {
            Poll::Ready(Ok(written)) => {
                this.budget = this.budget.saturating_sub(written);
                Poll::Ready(Ok(written))
            }
            other => other,
        }
    }
    fn poll_flush(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut self.get_mut().inner).poll_flush(cx)
    }
    fn poll_shutdown(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut self.get_mut().inner).poll_shutdown(cx)
    }
}

struct TlsEof<T>(T);

impl<T: AsyncRead + Unpin> AsyncRead for TlsEof<T> {
    fn poll_read(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buffer: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        match Pin::new(&mut self.get_mut().0).poll_read(cx, buffer) {
            Poll::Ready(Err(error)) if error.kind() == io::ErrorKind::UnexpectedEof => {
                Poll::Ready(Ok(()))
            }
            result => result,
        }
    }
}
impl<T: AsyncWrite + Unpin> AsyncWrite for TlsEof<T> {
    fn poll_write(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        bytes: &[u8],
    ) -> Poll<io::Result<usize>> {
        Pin::new(&mut self.get_mut().0).poll_write(cx, bytes)
    }
    fn poll_flush(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut self.get_mut().0).poll_flush(cx)
    }
    fn poll_shutdown(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut self.get_mut().0).poll_shutdown(cx)
    }
}

enum Either {
    Plain(SplitWrite<TcpStream>),
    Tls(TlsEof<tokio_rustls::client::TlsStream<SplitWrite<TcpStream>>>),
}

async fn run() -> io::Result<()> {
    let mut input = tokio::io::stdin();
    let data = frame(&mut input).await?;
    let config: Config = serde_json::from_slice(&data)
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "invalid_config"))?;
    let parent = config
        .socket
        .parent()
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "invalid_socket"))?;
    let meta = fs::symlink_metadata(parent)?;
    if !meta.is_dir() || meta.uid() != unsafe { libc::geteuid() } || meta.mode() & 0o077 != 0 {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "unsafe_socket_directory",
        ));
    }
    let mut roots = rustls::RootCertStore::empty();
    if let Some(path) = config.ca_file {
        let pem = fs::read(path)?;
        let mut reader = io::BufReader::new(pem.as_slice());
        for cert in rustls_pemfile::certs(&mut reader) {
            roots
                .add(cert?)
                .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "invalid_ca"))?;
        }
    } else {
        roots.extend(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());
    }
    if roots.is_empty() {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "empty_ca_store"));
    }
    let tls = rustls::ClientConfig::builder()
        .with_root_certificates(roots)
        .with_no_client_auth();
    let connector = TlsConnector::from(Arc::new(tls));
    let listener = UnixListener::bind(&config.socket)?;
    fs::set_permissions(&config.socket, fs::Permissions::from_mode(0o600))?;
    let mut output = tokio::io::stdout();
    output
        .write_all(b"{\"ready\":true,\"version\":1}\n")
        .await?;
    output.flush().await?;
    let slots = Arc::new(Semaphore::new(128));
    let mut workers = JoinSet::new();
    loop {
        tokio::select! {
            _=input.read_u8()=>break,
            accepted=listener.accept()=>{
                let (mut peer,_)=accepted?;
                if let Ok(slot)=slots.clone().try_acquire_owned() {
                    let connector=connector.clone();workers.spawn(async move {let _=connection(peer,connector,slot).await;});
                } else {let _=timeout(Duration::from_millis(250),respond(&mut peer,b"{\"ok\":false,\"error\":\"capacity\"}\n")).await;}
            }
            _=workers.join_next(),if !workers.is_empty()=>{}
        }
    }
    workers.abort_all();
    while workers.join_next().await.is_some() {}
    let _ = fs::remove_file(config.socket);
    Ok(())
}

fn main() {
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .max_blocking_threads(4)
        .enable_all()
        .build();
    match runtime.and_then(|runtime| runtime.block_on(run())) {
        Ok(()) => {}
        Err(error) => {
            eprintln!("Dagami network: {}", error.kind());
            std::process::exit(1);
        }
    }
}
