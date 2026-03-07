# ---- Builder Phase ----
FROM python:3.11 AS builder

WORKDIR /build

# Provide required system dependencies that some python modules need to compile
# python:3.11 non-slim inherently contains standard build-essential tools.
COPY requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /build/wheels -r requirements.txt

# ---- Final Runner Phase ----
FROM python:3.11-slim

WORKDIR /app

# Copy the pre-built, compiled binary wheels from builder phase
COPY --from=builder /build/wheels /wheels
COPY requirements.txt .

# Install dependencies using the wheels to avoid any C-compilation errors
RUN pip install --no-cache /wheels/* \
    && rm -rf /wheels

# Copy application code
COPY . .

# Create downloads directory
RUN mkdir -p downloads

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import telethon; print('healthy')" || exit 1

# Run the bot
CMD ["python", "bot.py"]
