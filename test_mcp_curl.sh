#!/bin/bash
curl -s -X POST http://localhost:8000/sessions/boss-zhipin-hr_8dd40f4a/task \
  -H "Content-Type: application/json" \
  -d '{
    "task": "导航到 boss 直聘的简历搜索页面 https://www.zhipin.com/web/boss/search",
    "model": "glm-5-turbo",
    "max_steps": 50
  }'
