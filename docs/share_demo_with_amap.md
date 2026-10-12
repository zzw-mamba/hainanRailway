# 分享海南路链 Demo，并显示高德底图

项目本机的根目录 `.env` 已有高德 Web 端 Key 和安全密钥。不要把 `.env`、`.env.local` 或整个项目目录上传到公开网站。网页的地图 Key 会进入浏览器，但安全密钥只应留在服务端代理。项目的正式构建默认请求同源 `/_AMapService`；`hainan-web/public/_worker.js` 提供 Cloudflare Pages 代理，安全密钥从 Pages Secret 读取。

## 一、在本机确认

在 `路链处理` 目录运行：

```bash
npm --prefix hainan-web install
npm --prefix hainan-web run dev -- --port 5173
```

打开 `http://127.0.0.1:5173/`，地图左下角应显示“高德地图 · GCJ-02”。开发模式使用本机 `.env` 中的 Key 和安全密钥。若显示“高德未连接”，先检查 Key 是否为“Web端（JS API）”、安全密钥是否与之配对，以及高德账号中的用量和域名配置。高德地图 JS API 必须能从访问者的浏览器连接到高德服务器。

## 二、检查要分享的数据

`hainan-web/public/data/hainan.json` 会完整发给每位访问者，包含路链几何、业务关联、桩号和门架等页面数据。分享前先确认这些数据允许公开。如果只想给指定人员查看，应先配置网站访问控制；链接本身不能保证保密。

## 三、构建可上传的网页

```bash
npm --prefix hainan-web run build
npm --prefix hainan-web run preview -- --port 4173
```

本地预览地址是 `http://127.0.0.1:4173/`。Vite 预览服务仅用于本机检查，不用作线上服务器。构建目录是 `hainan-web/dist/`，其中应有 `index.html`、`data/hainan.json` 和 `_worker.js`。正式构建不包含高德安全密钥；本机预览通过本地代理读取 `.env` 中的安全密钥。

## 四、已有“仅静态资源 Worker”：补上运行代码（推荐用于当前项目）

如果 Cloudflare 提示“不能将变量添加到只有静态资产的 Worker”，说明你创建的是 Workers 静态资源项目。仅拖入 `dist` 时，`dist/_worker.js` 只是一个文件，不会自动成为该 Worker 的运行代码。现在无需重建网页，只需用 Wrangler 把代理脚本与静态资源作为同一个 Worker 部署。Cloudflare 官方要求配置 `main` 指向脚本，`assets.directory` 指向构建目录，`assets.binding` 提供静态资源访问。

1. 在 `hainan-web` 目录复制 `wrangler.example.jsonc` 为 `wrangler.jsonc`，把 `name` 改成 Cloudflare 控制台中**现有 Worker 的准确名称**。`wrangler.jsonc` 是本机配置；不要把 Key 或安全密钥写入它。
2. 先运行 `npm run build`。构建目录的 `.assetsignore` 会让 Wrangler 不把 `_worker.js` 当作公开静态文件上传。
3. 运行 `npx wrangler login`，在浏览器完成 Cloudflare 登录。然后在 `hainan-web` 目录运行 `npx wrangler deploy`，选择与现有 Worker 相同的账号。`name` 相同会更新这个 Worker，网址继续使用现有的 `*.workers.dev`。
4. 部署成功后，在 Cloudflare 控制台进入该 Worker 的 **Settings → Variables and Secrets → Add**，添加 `AMAP_SECURITY_CODE`，填入本机根目录 `.env` 中对应的值，类型选择 **Secret / Encrypt**。现在该 Worker 已有运行代码，变量入口应可用。也可在 `hainan-web` 目录运行 `npx wrangler secret put AMAP_SECURITY_CODE`，在命令提示中粘贴值；不要把密钥直接写进命令行参数。
5. 刷新网址，地图左下角应显示“高德地图 · GCJ-02”。如果使用了高德 Key 的域名限制，还需把实际 `*.workers.dev` 域名加入允许列表。

`wrangler deploy` 会更新所填名称对应的线上 Worker；部署前务必核对名称。后续每次页面或数据更新，都运行 `npm run build`、`npx wrangler deploy`。如果这个 Worker 已绑定自定义域名，部署后也要从该域名检查地图。

## 五、重新创建为 Cloudflare Pages（另一种选择）

1. 登录 Cloudflare，进入 **Workers & Pages**，选择 **Create application → Get started → Drag and drop your files**。
2. 输入项目名，例如 `hainan-links-demo`。将**整个 `hainan-web/dist` 文件夹**拖入上传区域，完成首次部署。生成的网址形如 `https://hainan-links-demo.pages.dev/`。`dist/_worker.js` 会随静态文件上传并承担高德代理。
3. 进入该 Pages 项目的 **Settings → Variables and Secrets → Add**，新增名称为 `AMAP_SECURITY_CODE` 的值，填入本机根目录 `.env` 里与高德 Key 配对的 `AMAP_SECURITY_CODE`，选择 **Encrypt** 后保存。不要把它填入网页源码或 `VITE_` 变量。按 Cloudflare 的要求，在添加 Secret 后创建一次新的部署；重新上传同一个 `dist` 目录即可。
4. 如果高德控制台对该 Key 设置了允许的域名，将最终 `*.pages.dev` 域名和之后使用的自定义域名加入允许列表。公开网址中的高德底图需要使用访问者实际打开的域名。
5. 在无痕窗口打开公开网址，检查地图左下角是“高德地图 · GCJ-02”，底图和路链都显示。再打开 `https://你的域名/_AMapService/v3/config/district?keywords=%E6%B5%B7%E5%8D%97&subdistrict=0`，不应返回 `AMAP_SECURITY_CODE is not configured`。若地图仍不出现，检查浏览器开发者工具的 Network/Console 中的高德请求、Key 类型、域名和 Secret 是否配对。

这些步骤必须在 **Pages 项目**中完成；Workers 项目的静态资源上传入口不会把 `_worker.js` 识别成运行代码。Cloudflare Pages 的 Dashboard 直接上传支持构建目录中的 `_worker.js`。选择 Direct Upload 项目后，后续更新仍需重新构建并上传 `dist`。如果日后希望每次提交代码自动部署，可新建 Git 集成项目。

## 六、分享与后续更新

把 Pages 项目的公开网址发给使用者。网页支持地图查看、搜索筛选、路链详情、GIS 点和数据导出。公开静态站点不提供“重新生成路链”功能；要让其他人在线改变最大路链长度，需要单独部署受控的 Python 生成服务与数据存储，不能把本机 Vite 开发服务直接公开。

每次更新页面或数据后：

```bash
npm --prefix hainan-web run build
```

再在 Pages 项目中选择 **Create a new deployment**，上传新的 `hainan-web/dist`。

## 其他托管方式

如果使用自己的 Nginx 服务器，也可以部署 `dist`，并按高德官方的 [JS API 安全密钥代理说明](https://lbs.amap.com/api/javascript-api-v2/guide/abc/jscode) 配置同源 `/_AMapService`：`/v4/map/styles` 代理到 `webapi.amap.com`，其余路径代理到 `restapi.amap.com`，在服务端追加 `jscode`。项目默认使用这个代理前缀；无需修改前端。如果使用其他云托管平台，需要提供等价的服务端代理，或部署到支持 Cloudflare Pages `_worker.js` 的平台。

参考：[高德 Web端 Key 准备](https://lbs.amap.com/api/javascript-api-v2/prerequisites)、[高德安全密钥使用](https://lbs.amap.com/api/javascript-api-v2/guide/abc/jscode)、[Cloudflare Pages Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/)、[Cloudflare Pages Secret](https://developers.cloudflare.com/pages/functions/bindings/)。
