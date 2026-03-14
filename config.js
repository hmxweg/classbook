// config.js
// 终极版：自动区分开发环境与生产环境

let API_BASE_URL = "";

// 判断当前访问的端口，如果是我们本地测试用的 5500，就说明是本地/局域网开发环境
if (window.location.port === "5500" || window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost") {
    // 【本地开发环境】：跨端口调用后端
    const BACKEND_HOST = window.location.hostname;
    API_BASE_URL = `http://${BACKEND_HOST}:8000/api`;
    console.log("当前环境：本地局域网开发模式");
} else {
    // 【Ubuntu 生产环境】：走 Nginx 统一代理，自动继承当前的 HTTP/HTTPS 协议和域名
    // 注意：这里没有写死任何 IP 或端口！
    API_BASE_URL = `${window.location.protocol}//${window.location.host}/api`;
    console.log("当前环境：云服务器生产模式");
}