

openssl req -x509 -newkey rsa:4096 -keyout private.key -out cert.pem -sha256 -days 3650 -nodes -subj "/C=UK/L=London/O=Private/OU=Development/CN=Webserver"
mv private.key ./visonic_proxy/connections/httpserver/certs/private.key
mv cert.pem ./visonic_proxy/connections/httpserver/certs/cert.pem
