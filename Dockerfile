# Start from an official image that already has Python installed.
# "slim" is a smaller variant without build tools we don't need.
FROM python:3.12-slim

# All subsequent commands run from this directory inside the image.
WORKDIR /app

# Copy ONLY requirements.txt first, then install. Docker caches each step,
# so dependency installation is skipped on rebuilds unless requirements change.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the rest of the source code (changes here won't bust the pip cache).
COPY . .

# Document which port the app listens on (informational, doesn't open anything).
EXPOSE 8501

# The command the container runs when it starts.
# 0.0.0.0 makes Streamlit listen on all interfaces so traffic from
# outside the container can reach it.
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
