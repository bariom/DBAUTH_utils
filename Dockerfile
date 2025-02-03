# Usa un'immagine base Python
FROM python:3.11-slim

# Copia manualmente l'archivio OpenJDK nel container
COPY OpenJDK11U-jdk_x64_linux_hotspot_11.0.26_4.tar.gz /tmp/openjdk.tar.gz

# Estrai e configura OpenJDK
RUN mkdir -p /usr/lib/jvm \
    && tar -xvzf /tmp/openjdk.tar.gz -C /usr/lib/jvm \
    && rm -rf /tmp/openjdk.tar.gz

# Imposta Java come predefinito
ENV JAVA_HOME=/usr/lib/jvm/jdk-11.0.26+4
ENV PATH="$JAVA_HOME/bin:$PATH"

# Imposta la directory di lavoro
WORKDIR /app

# Copia i file del progetto
COPY . /app

# Installa le dipendenze Python
RUN pip install --no-cache-dir --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt

# Espone la porta per Dash
EXPOSE 8050

# Comando per avviare l'app
CMD ["python", "ComparePermissionsDocker.py"]
