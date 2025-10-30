FROM python:3.10-slim

#安装系统依赖、sshpass 和 openssh-client
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libssl-dev \
    sshpass \
    openssh-client \
  && rm -rf /var/lib/apt/lists/*

#确保 ~/.local/bin 在 PATH 中
ENV PATH="/root/.local/bin:${PATH}"
#忽略 Ansible 集合的版本检查
ENV ANSIBLE_COLLECTIONS_IGNORE_VERSION_CHECK=1

WORKDIR /app

#安装 Python 依赖（包括 ansible-core）
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

#安装所需的 Ansible Collection
RUN ansible-galaxy collection install \
      community.vmware \
      community.general \
      ansible.posix

#复制所有项目文件和 keys 目录
COPY keys/ ./keys/
COPY . .

EXPOSE 5000
CMD ["python", "app.py"]

