FROM python:3.9.1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y postgresql-client-11 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
COPY . .

RUN pip install -r requirements.txt

RUN chmod +x ./run_script.sh

CMD ["bash"]
