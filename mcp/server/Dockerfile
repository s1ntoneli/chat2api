FROM python:3.11-slim
WORKDIR /srv
RUN pip install --no-cache-dir fastmcp==4.1.2 mcp==2.3.0 "PyJWT[crypto]==2.15.1"
COPY . .
ENV PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
CMD ["python", "server.py"]
