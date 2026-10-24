# NOTICE —— templates/scene_globe_template.xml 来源说明

`scene_globe_template.xml` 是 SuperMap iDesktop 10i 自带样例工作空间
`CBD.smwu` 中「CBD」场景的 XML 片段（经 `getSceneXML` 导出），版权归
北京超图软件股份有限公司（SuperMap）所有。

该文件**不在本仓库 MIT 许可的覆盖范围内**，仅为互操作目的随包附带：
本桥的三维场景生成功能需要一份真实的球面场景 XML 作为结构模板，
该片段只作结构参考，不包含任何用户数据。

使用者可以（也建议）换成自己合法持有的 iDesktop 中导出的场景片段：
在 iDesktop 里打开任意含球面场景的工作空间，用
`ws._jobject.getScenes().getSceneXML("<场景名>")` 导出后替换本文件即可，
`scripts/make_scene_xml.py` 通过 `--template` 参数指定模板路径。
