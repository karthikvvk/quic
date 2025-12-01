from startsetup import *


env = load_env_vars()
host_ip, user, certi, sys, interface, outdir, srcdir, port,key,  dest_host = (
    env["host"],
    env["user"],
    env["certi"],
    env["system"],
    env["interface"],
    env["out_dir"],
    env["src"],
    env["port"],
    env["key"],
    env["dest_host"]
)

print(host_ip, user, certi, sys, interface, outdir, srcdir, port, key, dest_host)