# JMeter 运行方法

本次交付环境未找到 JMeter 命令，下载连通探测返回 HttpRequestException，因而此计划**尚未实际运行**。下面是安装 JMeter 后的补验方法，不代表已有压力测试通过结果。

用 JMeter 5.6.x 打开 `agenttestlab-readonly.jmx`。默认 2 个线程、每线程 5 次、1 秒启动，访问 `/health/ready`；可以通过 `-Jusers=5 -Jloops=20` 调整。只对本机自有开发服务测试。

```powershell
jmeter -n -t tests/jmeter/agenttestlab-readonly.jmx -Jusers=2 -Jloops=5 -l .local/jmeter-results.jtl -e -o .local/jmeter-html
```

预期：HTTP 200、响应包含 database=ok，结果文件与 HTML 报告生成。该脚本测基础服务可用性与延迟，不是 LLM 推理负载基准。用户主动提高并发前先观察 CPU、内存和数据库连接。每次 HTML 输出目录用新名称。
