

openssl req -x509 -newkey rsa:4096 -keyout private.key -out cert.pem -sha256 -days 3650 -nodes -subj "/C=UK/L=London/O=Private/OU=Development/CN=Webserver"
mv private.key ../visonic_proxy/visonic_proxy/connections/certs/private.key
mv cert.pem ../visonic_proxy/visonic_proxy/connections/certs/cert.pem
