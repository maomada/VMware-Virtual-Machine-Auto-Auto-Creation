from flask import Flask, render_template, request, jsonify
import configparser
import subprocess
import os
import json
import logging

app = Flask(__name__)

# 将日志也输出到文件，便于后端排查
logging.basicConfig(
    level=logging.INFO,
    filename='app.log',
    format='%(asctime)s %(levelname)s %(message)s'
)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/submit', methods=['POST'])
def submit():
    data = request.form.to_dict()
    # 前端已经拼好了 vm_folder
    vm_folder_full = data.get('vm_folder', '').strip()

    # 组装 ini 内容
    vm_params = {
        'vcenter_hostname': data.get('vcenter_hostname', '').strip(),
        'vcenter_username': data.get('vcenter_username', '').strip(),
        'vcenter_password': data.get('vcenter_password', '').strip(),
        'datacenter_name': data.get('datacenter_name', '').strip(),
        'vm_folder': vm_folder_full,
        'datastore_name': data.get('datastore_name', '').strip(),
        'vm_names': data.get('vm_names', '').strip(),
        'hostnames': data.get('hostnames', '').strip(),
        'vm_ips': data.get('vm_ips', '').strip(),
        'template': data.get('template', '').strip(),
        'memory_mb': data.get('memory_mb', '').strip(),
        'num_cpus': data.get('num_cpus', '').strip(),
        'disk_size_gb': data.get('disk_size_gb', '').strip(),
        'network_name': data.get('network_name', '').strip(),
        'netmask': data.get('netmask', '').strip(),
        'gateway': data.get('gateway', '').strip(),
        'dns_servers': data.get('dns_servers', '').strip(),
        'dns_suffix': data.get('dns_suffix', '').strip(),
        'cluster': data.get('cluster', '').strip(),
        'resource_pool': data.get('resource_pool', '').strip()
    }
    if data.get('esxi_hostname', '').strip():
        vm_params['esxi_hostname'] = data['esxi_hostname'].strip()

    # 写入 vm_params.ini
    ini_path = os.path.join(os.getcwd(), 'vm_params.ini')
    config = configparser.ConfigParser()
    config['vm_parameters'] = vm_params
    with open(ini_path, 'w') as cfg:
        config.write(cfg)

    # 调用 Ansible Playbook
    env = os.environ.copy()
    env["ANSIBLE_COLLECTIONS_IGNORE_VERSION_CHECK"] = "1"
    env["ANSIBLE_NOCOLOR"] = "1"
    try:
        result = subprocess.run(
            ['ansible-playbook', '-i', 'localhost,', 'create_vm.yml'],
            check=True,
            capture_output=True,
            text=True,
            env=env,
            timeout=3600  # 最长等一小时
        )
        stdout = result.stdout
        stderr = result.stderr
        returncode = result.returncode

        # ——— 方案一：直接从文件读取密码映射 ———
        password_file = '/tmp/vm_passwords.json'
        vm_passwords = {}
        try:
            with open(password_file, 'r', encoding='utf-8') as f:
                vm_passwords = json.load(f)
        except Exception as exc:
            logging.warning("读取密码映射文件失败：%s", exc)

        return jsonify({
            "message": "虚机创建任务已提交！",
            "passwords": vm_passwords,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": returncode
        }), 200

    except subprocess.CalledProcessError as e:
        stdout = e.stdout or ""
        stderr = e.stderr or ""
        returncode = e.returncode
        logging.error(
            "Ansible 执行失败，returncode=%s\nstdout:\n%s\nstderr:\n%s",
            returncode, stdout, stderr
        )
        return jsonify({
            "error": "执行 ansible-playbook 失败",
            "details": stdout + "\n" + stderr,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": returncode
        }), 500

    except subprocess.TimeoutExpired as e:
        logging.error("Ansible 执行超时：%s", str(e))
        return jsonify({
            "error": "执行 ansible-playbook 超时",
            "details": str(e)
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
