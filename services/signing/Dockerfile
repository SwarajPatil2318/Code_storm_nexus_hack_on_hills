ARG NEXUS_API_BASE
FROM ${NEXUS_API_BASE}
COPY custody.py /opt/nexus/services/signing/custody.py
COPY custody_entrypoint.py /opt/nexus/custody_entrypoint.py
COPY worker.py /opt/nexus/services/signing/worker.py
COPY entrypoint.py /opt/nexus/signing_entrypoint.py
ENTRYPOINT ["python", "-I", "/opt/nexus/signing_entrypoint.py"]
