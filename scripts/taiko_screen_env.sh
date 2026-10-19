# Source this file in the taiko screen; then use nb run normally.
export TAIKO_RUNTIME_ROOT=/home/sigaer/taiko
export TAIKO_SONG_PROFILE=center
export TAIKO_BOT_ENV_FILE=/home/sigaer/taiko/.env.prod
export BOT_POOL_METRICS_SERVICE_NAME=taiko
export FEATURE_SWITCH_DATA_DIR=/usr/lib/python3.11/site-packages/feature_handler/data
export BOT_GROUP_WHITELIST_PATH=/home/sigaer/config/bot_group_whitelist.json
export PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME

nb() {
    /opt/taiko-bot/current/bin/nb --python /opt/taiko-bot/current/bin/python --no-venv "$@"
}

cd /home/sigaer/taiko || return
