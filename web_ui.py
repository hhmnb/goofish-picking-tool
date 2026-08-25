# web_ui.py
import csv
import json
import threading
import webbrowser
from pathlib import Path
from flask import Flask, jsonify, request, render_template_string
from config import RESULT_FILE, BLACKLIST_FILE

app = Flask(__name__)

# 定义过滤结果和当前配置状态的文件路径（与 GUI 保持一致）
BASE_DIR = Path(__file__).parent
FILTERED_RESULT_FILE = BASE_DIR / "filtered_result.tsv"
CURRENT_FILTER_STATE_FILE = BASE_DIR / "current_filter_state.json"

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>闲鱼选品审核 - 网页版</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {
            background-color: #f8f9fa;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        }
        .container { max-width: 1400px; }
        .navbar {
            background-color: #ff5000;
            color: white;
            padding: 10px 0;
            margin-bottom: 20px;
        }
        .navbar h4 { color: white; margin: 0; }
        .config-panel {
            background: #fff;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.08);
            margin-bottom: 20px;
        }
        .config-panel h5 { margin-bottom: 10px; }
        .card {
            border: none;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            transition: transform 0.2s, box-shadow 0.2s;
            overflow: hidden;
        }
        .card:hover {
            transform: translateY(-4px);
            box-shadow: 0 6px 16px rgba(0,0,0,0.12);
        }
        .card-img-top {
            height: 180px;
            object-fit: cover;
            background-color: #eee;
        }
        .card-title {
            font-size: 1rem;
            font-weight: 500;
            color: #333;
            line-height: 1.4;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
            text-overflow: ellipsis;
            min-height: 2.8em;
            margin-bottom: 8px;
        }
        .card-text {
            margin-bottom: 4px;
        }
        .price {
            color: #ff5000;
            font-weight: bold;
            font-size: 1.2rem;
        }
        .seller-name {
            color: #888;
            font-size: 0.9rem;
        }
        .btn-link {
            text-decoration: none;
        }
        .btn-sm {
            padding: 2px 8px;
            font-size: 0.8rem;
        }
        #itemsContainer {
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
        }
        #itemsContainer .col {
            flex: 1 1 220px;
            max-width: 250px;
        }
    </style>
</head>
<body>
<div class="navbar">
    <div class="container">
        <h4>闲鱼选品审核 - 网页版</h4>
    </div>
</div>

<div class="container">
    <!-- 当前过滤配置展示 -->
    <div class="config-panel" id="configPanel">
        <h5>当前过滤配置</h5>
        <div id="configContent">加载中...</div>
    </div>

    <div class="row mb-3">
        <div class="col-md-6">
            <input type="text" id="searchInput" class="form-control" placeholder="搜索标题关键词...">
        </div>
        <div class="col-md-6 text-end">
            <label class="form-check-label me-2">
                <input type="checkbox" id="filterBlacklist" checked> 自动屏蔽黑名单商家
            </label>
            <button class="btn btn-primary btn-sm" onclick="loadItems()">刷新商品</button>
            <button class="btn btn-warning btn-sm" onclick="manageBlacklist()">管理黑名单</button>
            <button class="btn btn-danger btn-sm" onclick="batchBlacklist()">批量拉黑选中</button>
        </div>
    </div>

    <!-- 商品卡片容器 -->
    <div id="itemsContainer"></div>
</div>

<!-- 黑名单管理模态框 -->
<div class="modal fade" id="blacklistModal" tabindex="-1">
  <div class="modal-dialog">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title">管理黑名单</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <div class="mb-2">
          <input type="text" id="newBlacklistName" placeholder="输入卖家昵称添加" class="form-control">
          <button class="btn btn-sm btn-success mt-2" onclick="addBlacklist()">添加</button>
        </div>
        <ul class="list-group" id="blacklistList"></ul>
      </div>
    </div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
let allItems = [];
let blacklist = [];
let currentConfig = null;

async function loadItems() {
    const res = await fetch('/api/items');
    allItems = await res.json();
    applyFilter();
}

async function loadBlacklist() {
    const res = await fetch('/api/blacklist');
    blacklist = await res.json();
}

async function loadCurrentConfig() {
    const res = await fetch('/api/config');
    currentConfig = await res.json();
    renderConfig();
}

function renderConfig() {
    const container = document.getElementById('configContent');
    if (!currentConfig || currentConfig.error) {
        container.innerHTML = '<p class="text-danger">未找到当前配置信息</p>';
        return;
    }
    let html = '<ul class="list-unstyled">';
    html += `<li><strong>关键词：</strong>${currentConfig.keyword || '未设置'}</li>`;
    html += `<li><strong>过滤模式：</strong>${currentConfig.filter_mode || '未设置'}</li>`;
    html += `<li><strong>价格区间：</strong>${currentConfig.min_price || '不限'} ~ ${currentConfig.max_price || '不限'}</li>`;
    const models = currentConfig.model_keywords ? currentConfig.model_keywords.join(', ') : '无';
    html += `<li><strong>机型关键词：</strong>${models}</li>`;
    html += '</ul>';
    container.innerHTML = html;
}

function applyFilter() {
    const filter = document.getElementById('filterBlacklist').checked;
    const keyword = document.getElementById('searchInput').value.toLowerCase();
    const container = document.getElementById('itemsContainer');
    container.innerHTML = '';

    allItems.forEach(item => {
        const sellerName = item.seller_name || '';
        if (filter && blacklist.includes(sellerName)) return;
        if (keyword && !item.title.toLowerCase().includes(keyword)) return;

        const col = document.createElement('div');
        col.className = 'col';
        col.innerHTML = `
            <div class="card h-100">
                <div class="card-body">
                    <input type="checkbox" class="form-check-input item-checkbox float-end" data-seller-name="${sellerName}">
                    <h5 class="card-title"><a href="${item.link}" target="_blank" class="text-decoration-none text-dark">${item.title}</a></h5>
                    <p class="card-text"><span class="price">¥${item.price}</span></p>
                    <p class="card-text seller-name">${sellerName || '未知'}</p>
                    <button class="btn btn-sm btn-outline-danger mt-1" onclick="addBlacklistFromRow('${sellerName}')">拉黑</button>
                </div>
            </div>
        `;
        container.appendChild(col);
    });
}

function getSelectedSellerNames() {
    const names = [];
    document.querySelectorAll('.item-checkbox:checked').forEach(cb => {
        const name = cb.getAttribute('data-seller-name');
        if (name) names.push(name);
    });
    return [...new Set(names)];
}

async function addBlacklistFromRow(sellerName) {
    if (!sellerName) { alert('该商品缺少卖家昵称，无法拉黑'); return; }
    const res = await fetch('/api/blacklist', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({seller_name: sellerName})
    });
    if (res.ok) {
        await loadBlacklist();
        applyFilter();
    }
}

async function batchBlacklist() {
    const names = getSelectedSellerNames();
    if (names.length === 0) { alert('请先勾选要拉黑的商品'); return; }
    for (const name of names) {
        await fetch('/api/blacklist', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({seller_name: name})
        });
    }
    await loadBlacklist();
    applyFilter();
    alert('已批量拉黑选中卖家');
}

async function addBlacklist() {
    const input = document.getElementById('newBlacklistName');
    const sellerName = input.value.trim();
    if (!sellerName) return;
    const res = await fetch('/api/blacklist', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({seller_name: sellerName})
    });
    if (res.ok) {
        input.value = '';
        await loadBlacklist();
        renderBlacklist();
    }
}

async function removeBlacklist(sellerName) {
    const res = await fetch(`/api/blacklist?seller_name=${encodeURIComponent(sellerName)}`, {method: 'DELETE'});
    if (res.ok) {
        await loadBlacklist();
        renderBlacklist();
    }
}

function renderBlacklist() {
    const list = document.getElementById('blacklistList');
    list.innerHTML = '';
    blacklist.forEach(name => {
        const li = document.createElement('li');
        li.className = 'list-group-item d-flex justify-content-between align-items-center';
        li.innerHTML = `${name} <button class="btn btn-sm btn-outline-danger" onclick="removeBlacklist('${name}')">移除</button>`;
        list.appendChild(li);
    });
}

function manageBlacklist() {
    const modal = new bootstrap.Modal(document.getElementById('blacklistModal'));
    renderBlacklist();
    modal.show();
}

document.getElementById('filterBlacklist').addEventListener('change', applyFilter);
document.getElementById('searchInput').addEventListener('input', applyFilter);

// 初始化
loadBlacklist();
loadItems();
loadCurrentConfig();
</script>
</body>
</html>
'''


def load_filtered_items():
    """从过滤后的 TSV 文件读取商品列表（仅显示 GUI 过滤后的数据）"""
    items = []
    try:
        if FILTERED_RESULT_FILE.exists():
            with open(FILTERED_RESULT_FILE, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f, delimiter='\t')
                for row in reader:
                    items.append({
                        'title': row.get('title', ''),
                        'price': row.get('price', ''),
                        'link': row.get('link', ''),
                        'seller_name': row.get('seller_name', ''),
                        'seller_id': row.get('seller_id', '')
                    })
        else:
            print(f"过滤结果文件不存在: {FILTERED_RESULT_FILE}")
    except Exception as e:
        print(f"读取过滤结果文件失败: {e}")
    return items


def load_blacklist():
    """从黑名单文件读取卖家昵称列表"""
    if BLACKLIST_FILE.exists():
        try:
            with open(BLACKLIST_FILE, 'r', encoding='utf-8') as f:
                return [line.strip() for line in f if line.strip()]
        except Exception as e:
            print(f"读取黑名单文件失败: {e}")
            return []
    return []


def save_blacklist(blacklist):
    """保存黑名单到文件"""
    try:
        with open(BLACKLIST_FILE, 'w', encoding='utf-8') as f:
            for name in blacklist:
                f.write(name + '\n')
    except Exception as e:
        print(f"保存黑名单文件失败: {e}")


def load_current_filter_state():
    """读取当前激活的过滤配置（由 GUI 写入）"""
    if CURRENT_FILTER_STATE_FILE.exists():
        try:
            with open(CURRENT_FILTER_STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"读取当前过滤状态失败: {e}")
            return {}
    return {}


@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/items')
def api_items():
    # 返回过滤后的商品列表
    return jsonify(load_filtered_items())


@app.route('/api/config')
def api_config():
    # 返回当前过滤配置
    config = load_current_filter_state()
    if not config:
        return jsonify({'error': 'no config'})
    return jsonify(config)


@app.route('/api/blacklist', methods=['GET', 'POST', 'DELETE'])
def manage_blacklist():
    if request.method == 'GET':
        return jsonify(load_blacklist())
    elif request.method == 'POST':
        data = request.get_json(silent=True) or {}
        seller_name = data.get('seller_name', '').strip()
        if seller_name:
            blacklist = set(load_blacklist())
            blacklist.add(seller_name)
            save_blacklist(blacklist)
            return jsonify({'status': 'success', 'blacklist': list(blacklist)})
        return jsonify({'status': 'error', 'message': 'seller_name required'}), 400
    elif request.method == 'DELETE':
        seller_name = request.args.get('seller_name', '').strip()
        if seller_name:
            blacklist = set(load_blacklist())
            blacklist.discard(seller_name)
            save_blacklist(blacklist)
            return jsonify({'status': 'success', 'blacklist': list(blacklist)})
        return jsonify({'status': 'error', 'message': 'seller_name required'}), 400


_server = None
_server_thread = None


def start_web_server(port=5000):
    """启动 Flask 服务器并返回服务器对象（用于后续关闭）"""
    global _server, _server_thread

    # 如果已有服务器运行，先关闭旧服务器
    if _server_thread and _server_thread.is_alive():
        print("检测到旧服务器运行，正在关闭...")
        stop_server(_server)

    from werkzeug.serving import make_server
    _server = make_server('127.0.0.1', port, app, threaded=True)
    _server_thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _server_thread.start()
    # 使用 new=0 尽量在当前浏览器标签页打开，覆盖旧页面
    webbrowser.open(f'http://127.0.0.1:{port}', new=0)
    print(f"网页界面已启动: http://127.0.0.1:{port}")
    return _server


def stop_server(server=None):
    """停止服务器"""
    global _server, _server_thread
    target = server if server else _server
    if target:
        try:
            target.shutdown()
            if _server_thread:
                _server_thread.join(timeout=2)
            print("网页服务器已关闭")
        except Exception as e:
            print(f"关闭网页服务器失败: {e}")
        finally:
            if server is None:
                _server = None
                _server_thread = None
            else:
                if _server is target:
                    _server = None
                    _server_thread = None