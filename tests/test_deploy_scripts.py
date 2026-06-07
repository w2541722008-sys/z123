"""部署脚本上线门禁回归测试。"""

from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]


def _read_script(name: str) -> str:
    return (PROJECT_DIR / name).read_text(encoding="utf-8")


def test_deploy_rsync_preserves_runtime_state_directories():
    deploy = _read_script("deploy.sh")

    assert "--exclude='avatars'" in deploy
    assert "--exclude='backend/data'" in deploy


def test_deploy_rsync_excludes_local_only_artifacts():
    deploy = _read_script("deploy.sh")

    assert "--exclude='.mypy_cache'" in deploy
    assert "--exclude='tests'" in deploy
    assert "--exclude='.scratch'" in deploy


def test_deploy_migration_failure_blocks_restart():
    deploy = _read_script("deploy.sh")

    migration_block_start = deploy.index("# 执行数据库迁移")
    restart_block_start = deploy.index("cd /opt/aifriend", migration_block_start + 1)
    migration_block = deploy[migration_block_start:restart_block_start]

    assert "数据库迁移失败" in migration_block
    assert "exit 1" in migration_block


def test_deploy_dependency_install_failure_blocks_restart():
    deploy = _read_script("deploy.sh")

    dependency_block_start = deploy.index("if [[ -f requirements.txt ]]")
    migration_block_start = deploy.index("# 执行数据库迁移")
    dependency_block = deploy[dependency_block_start:migration_block_start]

    assert "依赖安装失败" in dependency_block
    assert "exit 1" in dependency_block


def test_deploy_health_check_requires_json_status_ok():
    deploy = _read_script("deploy.sh")

    assert "health_status" in deploy
    assert 'status") == "ok"' in deploy


def test_rollback_preserves_uploaded_avatars():
    rollback = _read_script("rollback.sh")

    assert "/tmp/aifriend_avatars_backup" in rollback
    assert "$CURRENT_DIR/avatars" in rollback
