FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies including curl for health checks and openssl for SSL
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    openssl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY smart_agent/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY smart_agent/ ./smart_agent/
COPY lambda_handler.py .

# Generate self-signed SSL certificate for HTTPS support
RUN mkdir -p /app/ssl && \
    openssl req -x509 -newkey rsa:4096 -keyout /app/ssl/server.key -out /app/ssl/server.crt -days 365 -nodes \
    -subj "/C=US/ST=State/L=City/O=Organization/CN=localhost"

# Create non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser appuser
RUN chown -R appuser:appuser /app
USER appuser

# Expose ports for HTTP and HTTPS
EXPOSE 8000
EXPOSE 8443

# Set environment variables for ECS
ENV LOCAL_RUN=false
ENV PYTHONPATH=/app
ENV USE_SSL=true
ENV APP_PORT=8443

# Health check for HTTPS
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -k -f https://localhost:8443/status || curl -f http://localhost:8000/status || exit 1

# Start the FastAPI application with SSL support
CMD ["python", "smart_agent/main.py"]