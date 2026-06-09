"""部署脚本上线门禁回归测试。"""

from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]


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
    assert "--exclude='.agents'" in deploy
    assert "--exclude='.claude'" in deploy
    assert "--exclude='.codex'" in deploy
    assert "--exclude='.idea'" in deploy
    assert "--exclude='output'" in deploy


def test_deploy_migration_failure_blocks_restart():
    deploy = _read_script("deploy.sh")

    migration_block_start = deploy.index("# 执行数据库迁移")
    restart_block_start = deploy.index("cd /opt/aifriend", migration_block_start + 1)
    migration_block = deploy[migration_block_start:restart_block_start]

    assert "数据库迁移失败" in migration_block
    assert "exit 1" in migration_block


def test_deploy_runs_alembic_from_backend_venv():
    deploy = _read_script("deploy.sh")

    assert "SKIP_DB_MIGRATION" in deploy
    assert "SKIP_DB_MIGRATION=${SKIP_DB_MIGRATION:-0}" in deploy
    assert 'ALEMBIC_BIN="/opt/aifriend/backend/venv/bin/alembic"' in deploy
    assert '"$ALEMBIC_BIN" -c alembic.ini upgrade head' in deploy
    assert "python3 -m alembic" not in deploy


def test_deploy_and_rollback_use_same_backup_patterns():
    deploy = _read_script("deploy.sh")
    rollback = _read_script("rollback.sh")

    for pattern in ("/opt/aifriend_backup_*", "/opt/aifriend_20*", '"$HOME"/aifriend_20*', '"$HOME"/aifriend_backup_*'):
        assert pattern in deploy
        assert pattern in rollback


def test_restart_fallback_binds_loopback_and_prefers_systemd():
    restart = _read_script("restart.sh")

    assert "systemctl is-enabled aifriend" in restart
    assert "--host 127.0.0.1" in restart
    assert "--host 0.0.0.0" not in restart


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
    assert 'health_status != "ok"' in deploy
    assert 'fetch("/")' in deploy
    assert 'fetch("/api/characters")' in deploy
    assert 'isinstance(characters_data, list)' in deploy


def test_rollback_preserves_uploaded_avatars():
    rollback = _read_script("rollback.sh")

    assert "/tmp/aifriend_avatars_backup" in rollback
    assert "$CURRENT_DIR/avatars" in rollback
