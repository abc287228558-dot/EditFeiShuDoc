#!/bin/bash
# 环境切换脚本

ENV=$1

if [ -z "$ENV" ]; then
    echo "使用方法: ./switch_env.sh [prod|test]"
    echo ""
    echo "当前环境:"
    if [ -f config.json ]; then
        APP_ID=$(cat config.json | grep '"app_id"' | head -1 | cut -d'"' -f4)
        WIKI_URL=$(cat config.json | grep '"wiki_url"' | head -1 | cut -d'"' -f4)
        
        if [[ "$APP_ID" == "cli_a9200e9641fadbc0" ]]; then
            echo "  ✅ 正式环境 (prod)"
        elif [[ "$APP_ID" == "cli_a92cd34869b9dbd6" ]]; then
            echo "  ✅ 测试环境 (test)"
        else
            echo "  ⚠️  未知环境"
        fi
        
        echo "  App ID: $APP_ID"
        echo "  Wiki URL: $WIKI_URL"
    else
        echo "  ❌ config.json 不存在"
    fi
    exit 1
fi

if [ "$ENV" == "prod" ]; then
    echo "🔄 切换到正式环境..."
    cp config.prod.json config.json
    echo "✅ 已切换到正式环境"
    echo "  App ID: cli_a9200e9641fadbc0"
    echo "  Wiki URL: https://my.feishu.cn/wiki/PWMUwFVPni4WY9kRunEckmW9n0g"
elif [ "$ENV" == "test" ]; then
    echo "🔄 切换到测试环境..."
    cp config.test.json config.json
    echo "✅ 已切换到测试环境"
    echo "  App ID: cli_a92cd34869b9dbd6"
    echo "  Wiki URL: https://vcn13vbsobtc.feishu.cn/wiki/WuLowQPlOigCT9kQ089chCfun2e"
else
    echo "❌ 无效的环境: $ENV"
    echo "请使用: prod 或 test"
    exit 1
fi
