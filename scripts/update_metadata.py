import json
import os
import sys
import urllib.request
from pathlib import Path
from datetime import datetime, timezone
from collections import OrderedDict

GITHUB_TOKEN = os.getenv("HUB_TOKEN") or os.getenv("GITHUB_TOKEN")

def load_yaml_content(yaml_content):
    """加载YAML内容（假设验证已在前一步完成）"""
    try:
        import yaml
        if isinstance(yaml_content, str):
            return yaml.safe_load(yaml_content) or {}
        return yaml_content if isinstance(yaml_content, dict) else {}
    except Exception as e:
        print(f"Warning: Failed to parse YAML: {e}", file=sys.stderr)
        return {}

def parse_owner_repo(repo_url: str):
    """从repo URL解析owner和repo名称"""
    if not repo_url:
        return "", ""
    parts = repo_url.rstrip("/").split("/")
    if len(parts) >= 2:
        return parts[-2], parts[-1]
    return "", ""

def fetch_repo_info(owner, repo):
    """从GitHub API获取仓库信息"""
    if not (owner and repo):
        return {}
    url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                return json.loads(response.read().decode())
    except Exception:
        pass
    return {}

def detect_logo(owner, repo, branch):
    """检测logo.png是否存在"""
    if not (owner and repo):
        return ""
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/logo.png"
    headers = {}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    
    try:
        req = urllib.request.Request(url, headers=headers, method="HEAD")
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                return url
    except Exception:
        pass
    return ""

def convert_to_official_format(plugin_data):
    """
    转换为官方格式
    注意：假设plugin_data已经通过validate_metadata.py验证和修复
    """
    # 获取repo URL（已经验证过，确保存在）
    repo_url = (plugin_data.get("repo") or "").rstrip("/")
    owner, repo = parse_owner_repo(repo_url)

    # 插件主键：metadata.yaml 的 name；否则回退为 GitHub 仓库名（与 JSON 顶层键一致）
    plugin_id = (plugin_data.get("name") or "").strip() or repo or "unknown_plugin"

    # tags已经在前面的验证中确保是list类型，这里只需要确保不为None
    tags = plugin_data.get("tags") or []

    # 获取GitHub仓库信息（stars、更新时间等）
    info = fetch_repo_info(owner, repo)
    stars = info.get("stargazers_count") or 0
    updated_at = info.get("pushed_at") or info.get("updated_at")
    if not updated_at:
        updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    branch = info.get("default_branch") or "main"

    # 检测logo
    logo = detect_logo(owner, repo, branch)
    
    # 构建写入 plugins.json 的对象（不含 name：主键仅为顶层键）
    formatted = {
        "display_name": plugin_data.get("display_name", ""),
        "desc": plugin_data.get("desc", ""),
        "author": plugin_data.get("author", ""),
        "repo": repo_url,
        "tags": tags,  # 已经是list类型
        "social_link": f"https://github.com/{owner}" if owner else "",
        "stars": stars,
        "version": plugin_data.get("version", ""),
        "updated_at": updated_at,
        "logo": logo,
    }
    return plugin_id, formatted

def update_plugin_metadata(plugin_yaml):
    """
    更新插件元数据
    注意：传入的plugin_yaml应该已经通过validate_metadata.py验证
    """
    plugin_data = load_yaml_content(plugin_yaml)

    # 读取现有的plugins.json
    plugins_file = Path("plugins.json")
    if plugins_file.exists():
        with plugins_file.open("r", encoding="utf-8") as f:
            all_plugins = json.load(f)
    else:
        all_plugins = {}

    # 只有新插件或版本号发生变化时才更新。
    # stars、updated_at 等动态字段可能在版本未变化时发生波动；如果继续重写
    # plugins.json，会给 Hub 制造没有实际发布意义的提交记录。
    repo_url = (plugin_data.get("repo") or "").rstrip("/")
    _, repo = parse_owner_repo(repo_url)
    plugin_id = (plugin_data.get("name") or "").strip() or repo or "unknown_plugin"
    incoming_version = str(plugin_data.get("version") or "").strip()
    existing_data = all_plugins.get(plugin_id)
    if isinstance(existing_data, dict):
        existing_version = str(existing_data.get("version") or "").strip()
        if incoming_version == existing_version:
            print(
                f"Skipped plugin: {plugin_id} "
                f"(version unchanged: {incoming_version or '<empty>'})"
            )
            return plugin_id, existing_data, False

    # 转换为官方格式
    plugin_id, formatted_data = convert_to_official_format(plugin_data)
    
    # 使用OrderedDict保持顺序，新插件插入到最前面
    ordered_plugins = OrderedDict()
    ordered_plugins[plugin_id] = formatted_data
    for key, value in all_plugins.items():
        if key != plugin_id:  # 避免重复
            ordered_plugins[key] = value

    # 去掉历史条目中的冗余 name（主键只在顶层键）
    for entry in ordered_plugins.values():
        if isinstance(entry, dict):
            entry.pop("name", None)

    # 保存到文件
    with plugins_file.open("w", encoding="utf-8") as f:
        json.dump(ordered_plugins, f, ensure_ascii=False, indent=2)

    return plugin_id, formatted_data, True

if __name__ == "__main__":
    plugin_yaml = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PLUGIN_YAML", "{}")
    plugin_id, updated_data, changed = update_plugin_metadata(plugin_yaml)
    if changed:
        print(f"Updated plugin: {plugin_id}")
    print(json.dumps({plugin_id: updated_data}, ensure_ascii=False, indent=2))
