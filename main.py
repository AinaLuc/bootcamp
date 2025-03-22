from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
import subprocess
import os
from pydantic import BaseModel

app = FastAPI()

WORDPRESS_DIR = "/var/www/"
NGINX_CONFIG_PATH = "/etc/nginx/sites-available/"
NGINX_ENABLED_PATH = "/etc/nginx/sites-enabled/"

# 🟢 Function to Install WordPress, Nginx, and SSL
def install_wordpress(domain: str):
    domain_path = f"{WORDPRESS_DIR}{domain}"
    
    if os.path.exists(domain_path):
        print(f"Domain {domain} already installed.")
        return
    
    os.makedirs(domain_path, exist_ok=True)
    subprocess.run(f"wget https://wordpress.org/latest.tar.gz -P {domain_path}", shell=True)
    subprocess.run(f"tar -xzf {domain_path}/latest.tar.gz -C {domain_path} --strip-components=1", shell=True)
    subprocess.run(f"rm {domain_path}/latest.tar.gz", shell=True)
    
    subprocess.run(f"chown -R www-data:www-data {domain_path}", shell=True)
    subprocess.run(f"chmod -R 755 {domain_path}", shell=True)
    
    nginx_conf = f"""
    server {{
        listen 80;
        server_name {domain};

        root {domain_path};
        index index.php index.html index.htm;

        location / {{
            try_files $uri $uri/ /index.php?$args;
        }}

        location ~ \.php$ {{
            include snippets/fastcgi-php.conf;
            fastcgi_pass unix:/run/php/php7.4-fpm.sock;
            fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
            include fastcgi_params;
        }}
    }}
    """
    
    conf_file = f"{NGINX_CONFIG_PATH}{domain}"
    with open(conf_file, "w") as f:
        f.write(nginx_conf)
    
    subprocess.run(f"ln -s {conf_file} {NGINX_ENABLED_PATH}{domain}", shell=True)
    subprocess.run("systemctl restart nginx", shell=True)
    subprocess.run(f"certbot --nginx -d {domain} --non-interactive --agree-tos -m admin@{domain}", shell=True)

    print(f"✅ WordPress installed at {domain}")

class InstallRequest(BaseModel):
    domain: str

@app.post("/install/")
async def install_domain(request: Request, install_data: InstallRequest):
    if "globaltrade.us" not in request.headers.get("referer", ""):
        raise HTTPException(status_code=403, detail="Access Denied")
    domain = install_data.domain

    install_wordpress(domain)
    
    return {"message": "Installation completed", "setup_url": f"https://{domain}/wp-admin/install.php"}

# 🟢 Serve Vue.js Interface Only to Requests from lumentrade.us
@app.get("/site", response_class=HTMLResponse)
async def serve_vue_ui(request: Request):
    referer = request.headers.get("referer", "")
    
    if "globalform.us" not in referer and "globalform.us" not in referer:
        raise HTTPException(status_code=403, detail="Access Denied")

    vue_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>WordPress Installer</title>
        <style>
            body { font-family: Arial, sans-serif; text-align: center; margin-top: 50px; }
            input { padding: 10px; width: 300px; margin-bottom: 10px; }
            button { padding: 10px; background-color: blue; color: white; border: none; cursor: pointer; }
            .error { color: red; }
        </style>
    </head>
    <body>
        <h2>Install WordPress</h2>
        <input id="domain" placeholder="Enter domain (e.g. example.com)" />
        <button onclick="installWordPress()">Install</button>
        <p id="message"></p>

        <script>
            async function installWordPress() {
                const domain = document.getElementById('domain').value;
                if (!domain) {
                    document.getElementById('message').innerText = "Enter a domain!";
                    return;
                }
                
                try {
                    let response = await fetch('/install/', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'Referer': 'https://lumentrade.us' },
                        body: JSON.stringify({ domain })
                    });
                    let data = await response.json();
                    
                    if (response.ok) {
                        document.getElementById('message').innerHTML = "✅ WordPress Installed! <a href='" + data.setup_url + "' target='_blank'>Setup Here</a>";
                    } else {
                        document.getElementById('message').innerText = data.detail;
                    }
                } catch (error) {
                    document.getElementById('message').innerText = "Error installing WordPress";
                }
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=vue_template)
