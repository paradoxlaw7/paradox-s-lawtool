FROM python:3.12-slim
WORKDIR /app
COPY server.py ai_gateway.py errors.py documents.py harness_bridge.py agent_tasks.py agent_quality.py knowledge.py knowledge_seed.json demo.json ./
COPY public ./public
RUN useradd --uid 10001 --create-home workspace && mkdir -p /app/data && chown -R workspace:workspace /app
USER workspace
ENV PYTHONUNBUFFERED=1 HOST=0.0.0.0 PORT=8765 DATA_DIR=/app/data
EXPOSE 8765
CMD ["python", "server.py"]
