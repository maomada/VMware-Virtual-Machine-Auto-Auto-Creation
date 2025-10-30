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
        'resource_pool': data.get('resource_pool', '').strip(),
        'scheduling_strategy': data.get('scheduling_strategy', 'cluster').strip()
    }
    
    # 处理ESXi主机配置
    esxi_hostnames = data.get('esxi_hostnames', '').strip()
    if esxi_hostnames:
        vm_params['esxi_hostnames'] = esxi_hostnames
        logging.info(f"ESXi主机配置: {esxi_hostnames}")
    
    # 记录调度策略
    strategy = vm_params['scheduling_strategy']
    logging.info(f"调度策略: {strategy}")
    
    if strategy == 'single-esxi' and not esxi_hostnames:
        return jsonify({
            "error": "单ESXi主机模式下必须指定ESXi主机",
            "details": "请在调度策略中选择具体的ESXi主机"
        }), 400
    
    if strategy == 'multi-esxi':
        vm_names = data.get('vm_names', '').strip()
        if vm_names and esxi_hostnames:
            vm_count = len(vm_names.split(','))
            esxi_count = len(esxi_hostnames.split(','))
            if vm_count != esxi_count:
                return jsonify({
                    "error": f"多ESXi主机模式下，ESXi主机数量({esxi_count})必须与VM数量({vm_count})相等",
                    "details": f"请确保每个VM都有对应的ESXi主机分配"
                }), 400

    # 写入 vm_params.ini
    ini_path = os.path.join(os.getcwd(), 'vm_params.ini')
    config = configparser.ConfigParser()
    config['vm_parameters'] = vm_params
    with open(ini_path, 'w', encoding='utf-8') as cfg:
        config.write(cfg)
    
    logging.info(f"配置文件已写入: {ini_path}")
    logging.info(f"VM配置: {vm_params}")

    # 调用 Ansible Playbook
    env = os.environ.copy()
    env["ANSIBLE_COLLECTIONS_IGNORE_VERSION_CHECK"] = "1"
    env["ANSIBLE_NOCOLOR"] = "1"
    
    try:
        logging.info("开始执行 Ansible Playbook...")
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
        
        logging.info("Ansible 执行成功")
        logging.info(f"stdout: {stdout}")
        if stderr:
            logging.warning(f"stderr: {stderr}")

        # 从文件读取密码映射
        password_file = '/tmp/vm_passwords.json'
        vm_passwords = {}
        try:
            with open(password_file, 'r', encoding='utf-8') as f:
                vm_passwords = json.load(f)
            logging.info(f"成功读取密码映射: {vm_passwords}")
        except Exception as exc:
            logging.warning(f"读取密码映射文件失败：{exc}")

        return jsonify({
            "message": "虚机创建任务完成！",
            "passwords": vm_passwords,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": returncode,
            "scheduling_info": {
                "strategy": strategy,
                "esxi_hosts": esxi_hostnames.split(',') if esxi_hostnames else [],
                "vm_count": len(vm_params['vm_names'].split(',')) if vm_params['vm_names'] else 0
            }
        }), 200

    except subprocess.CalledProcessError as e:
        stdout = e.stdout or ""
        stderr = e.stderr or ""
        returncode = e.returncode
        logging.error(
            f"Ansible 执行失败，returncode={returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"
        )
        
        # 分析错误类型
        error_analysis = analyze_error(stdout, stderr)
        
        return jsonify({
            "error": "执行 ansible-playbook 失败",
            "details": error_analysis,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": returncode
        }), 500

    except subprocess.TimeoutExpired as e:
        logging.error(f"Ansible 执行超时：{str(e)}")
        return jsonify({
            "error": "执行 ansible-playbook 超时",
            "details": f"任务执行超过1小时限制：{str(e)}"
        }), 500


@app.route('/logs', methods=['GET'])
def get_logs():
    """提供后端运行日志，便于前端查看部署过程"""

    log_path = os.path.join(os.getcwd(), 'app.log')

    try:
        if not os.path.exists(log_path):
            return jsonify({
                "logs": "",
                "message": "日志文件暂不可用，请稍后重试。"
            }), 200

        with open(log_path, 'r', encoding='utf-8', errors='ignore') as log_file:
            lines = log_file.readlines()

        # 仅返回最新的部分日志，避免前端加载过大文件
        tail_size = 500
        recent_lines = lines[-tail_size:]
        logs_text = ''.join(recent_lines)

        return jsonify({
            "logs": logs_text
        }), 200

    except Exception as exc:
        logging.error(f"读取日志文件失败: {exc}")
        return jsonify({
            "error": "日志读取失败",
            "details": str(exc)
        }), 500

def analyze_error(stdout, stderr):
    """分析Ansible错误并提供有用的错误信息"""
    
    # 常见错误模式
    error_patterns = {
        "Permission denied": "SSH连接被拒绝，可能是密码错误或SSH服务未启动",
        "timed out waiting for ping": "无法连接到虚机，可能是网络配置问题或虚机未完全启动",
        "UNREACHABLE": "无法访问目标主机，请检查网络连接和SSH配置", 
        "Failed to connect to the host via ssh": "SSH连接失败，请检查主机可达性和SSH服务状态",
        "template not found": "指定的模板不存在，请检查模板名称是否正确",
        "insufficient resources": "资源不足，请检查ESXi主机的CPU、内存和存储空间",
        "datastore not found": "指定的数据存储不存在",
        "network not found": "指定的网络不存在",
        "cluster not found": "指定的集群不存在"
    }
    
    combined_output = (stdout + stderr).lower()
    
    for pattern, description in error_patterns.items():
        if pattern.lower() in combined_output:
            return f"{description}\n\n原始错误：{stdout}\n{stderr}"
    
    # 如果没有匹配到已知错误，返回原始错误信息
    return f"未知错误，请查看详细日志：\n{stdout}\n{stderr}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
