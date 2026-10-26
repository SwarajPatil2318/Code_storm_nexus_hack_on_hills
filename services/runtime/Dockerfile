FROM python@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de
ARG WORKLOAD_ROLE
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 NEXUS_WORKLOAD_ROLE=${WORKLOAD_ROLE}
WORKDIR /opt/runtime
COPY wire.py worker.py gateway.py bootstrap.py providers.py evaluation_rules.py ./
RUN ["/usr/local/bin/python", "-I", "-c", "import pathlib,shutil; [shutil.rmtree(p,ignore_errors=True) if pathlib.Path(p).is_dir() and not pathlib.Path(p).is_symlink() else pathlib.Path(p).unlink(missing_ok=True) for p in ['/bin','/sbin','/usr/bin','/usr/sbin']]; [p.unlink() for p in pathlib.Path('/usr/local/bin').iterdir() if p.name not in {'python','python3','python3.12'} and (p.is_file() or p.is_symlink())]"]
USER 10001:10001
ENTRYPOINT ["python", "-I", "/opt/runtime/bootstrap.py"]
