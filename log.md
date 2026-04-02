# 运行
./.venv/bin/python web_control_server.py --config config.json --port 8010

# 切换到测试环境
./switch_env.sh test

# 切换到正式环境
./switch_env.sh prod

# 切换到正式环境（四月）
./switch_env.sh prod-apr

# 查看当前环境
./switch_env.sh

# Mac 的 SMB 方式
smb://192.168.1.113/共享文件夹