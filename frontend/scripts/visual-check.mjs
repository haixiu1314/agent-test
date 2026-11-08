// 在生产构建上检查三个屏宽；仅使用真实 MySQL 集成验收账号的数据。
import { chromium } from '@playwright/test';
import fs from 'node:fs';
const directory=new URL('../../docs/evidence/',import.meta.url);
const fixture=JSON.parse(fs.readFileSync(new URL('mysql-check.json',directory),'utf8').replace(/^\uFEFF/,''));
const browser=await chromium.launch({executablePath:process.env.ATL_BROWSER_PATH||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
const page=await browser.newPage();
const result=[];
try {
  const response=await page.request.post('http://127.0.0.1:8000/api/v1/auth/login',{data:{username:fixture.retained_test_username,password:'integration-only-password-123'}});
  if(!response.ok())throw new Error('Fixture login failed');
  const {access_token}=await response.json();
  await page.goto('http://127.0.0.1:5173/login');
  for(const width of [1440,768,390]){
    await page.setViewportSize({width,height:900});
    await page.screenshot({path:new URL(`login-${width}.png`,directory).pathname.replace(/^\/([A-Za-z]:)/,'$1'),fullPage:true});
  }
  await page.evaluate(token=>sessionStorage.setItem('atl_token',token),access_token);
  for(const route of ['projects','agents','system']){
    await page.goto('http://127.0.0.1:5173/'+route);
    await page.waitForLoadState('networkidle');
    for(const width of [1440,768,390]){
      await page.setViewportSize({width,height:900});
      const facts=await page.evaluate(()=>{
        const visible=e=>e.getBoundingClientRect().width>0&&e.getBoundingClientRect().height>0;
        const elements=[...document.querySelectorAll('main *,header *,nav *')].filter(visible);
        return {overflow:document.documentElement.scrollWidth>window.innerWidth,h1:document.querySelectorAll('h1').length,
          tinyText:elements.filter(e=>e.childNodes.length&&[...e.childNodes].some(n=>n.nodeType===3&&n.textContent.trim())&&parseFloat(getComputedStyle(e).fontSize)<11).length,
          font:getComputedStyle(document.body).fontFamily};
      });
      if(facts.overflow||facts.h1!==1||facts.tinyText)throw new Error(JSON.stringify({route,width,...facts}));
      result.push({route,width,...facts});
      await page.screenshot({path:new URL(`${route}-${width}.png`,directory).pathname.replace(/^\/([A-Za-z]:)/,'$1'),fullPage:true});
    }
  }
  fs.writeFileSync(new URL('visual-check.json',directory),JSON.stringify({status:'passed',checks:result},null,2));
  console.log('Visual measurements passed at 1440, 768 and 390px for projects, agents and system.');
} finally {await browser.close()}
