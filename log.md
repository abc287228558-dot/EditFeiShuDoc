# 运行
./.venv/bin/python web_control_server.py --config config.json --port 8010

# 切换到测试环境
./switch_env.sh test

# 切换到正式环境
./switch_env.sh prod

# 查看当前环境
./switch_env.sh