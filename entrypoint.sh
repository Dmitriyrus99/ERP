#!/bin/bash
set -e

cd /home/frappe/frappe-bench

# 安裝 ERPNext app
bench get-app --branch version-14 erpnext

# 建立網站並安裝 app（僅當未建立時）
if [ ! -d "./sites/${SITE_NAME}" ]; then
  bench new-site ${SITE_NAME} \
    --mariadb-root-password ${MYSQL_ROOT_PASSWORD} \
    --admin-password ${ADMIN_PASSWORD} \
    --no-mariadb-socket
  bench --site ${SITE_NAME} install-app ${INSTALL_APPS}
fi

# 啟動服務
bench start
