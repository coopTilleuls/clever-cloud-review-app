#!/bin/env python

import argparse
import json
import os
import stat
import subprocess
from invoke import run
import sys
import tempfile
import time
from datetime import date, datetime


def get_deployments(clever_cli, app_alias):
    activity_output = run(f'{clever_cli} activity --format=json --alias {app_alias}')
    return json.loads(activity_output.stdout)

def deployment_logs(clever_cli, deployment, app_alias):
    after = datetime.fromtimestamp(deployment.get("date")/1000).isoformat()
    uuid = deployment.get("uuid")
    cmd = f'{clever_cli} logs --deployment-id {uuid} --after {after} --alias {app_alias}'
    fg = run(cmd, asynchronous=True)
    return fg


def deploy():
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch", required=True)
    parser.add_argument("--app-alias", required=True)
    parser.add_argument("--clever-cli", default="clever")

    args = parser.parse_args()
    branch = args.branch
    clever_cli = args.clever_cli
    app_alias = args.app_alias

    if not os.getenv("CLEVER_TOKEN") or not os.getenv("CLEVER_SECRET"):
        sys.exit("Environment variables CLEVER_TOKEN & CLEVER_SECRET are mandatory")

    applications_data = subprocess.check_output([clever_cli, "applications", "--json"])
    try:
        [deploy_url] = [info["deploy_url"] for info in json.loads(applications_data) if info["alias"] == app_alias]
    except ValueError:
        sys.exit(f"Could not find the deploy url for {app_alias} - check your linked applications")

    known_deployment_uids = {d["uuid"] for d in get_deployments(clever_cli, app_alias)}

    # TODO(xfernandez: switch to delete_on_close=False in 3.12
    with tempfile.NamedTemporaryFile(prefix="clever_git_alias", delete=False) as f:
        f.write(b"""#!/bin/bash
case "$1" in
    Username*) echo "$CLEVER_TOKEN" ;;
    Password*) echo "$CLEVER_SECRET" ;;
esac
""")
        f.close()
        os.chmod(f.name, stat.S_IRUSR | stat.S_IXUSR)
        subprocess.check_call(
            ["git", "push", deploy_url, f"{branch}:master", "--force", "--progress"],
            env={
                "CLEVER_TOKEN": os.environ["CLEVER_TOKEN"],
                "CLEVER_SECRET": os.environ["CLEVER_SECRET"],
                "GIT_ASKPASS": f.name,
            },
        )
    os.remove(f.name)

    for _attempt in range(10):
        new_deployments = [d for d in get_deployments(clever_cli, app_alias) if d["uuid"] not in known_deployment_uids]
        if new_deployments:
            break
        time.sleep(1)
    else:
        sys.exit("No new deployment despite successfull push")

    if len(new_deployments) != 1:
        print(f"Multiple new deployements - all bets are off: {new_deployments}")

    deployment_uid = new_deployments[0]["uuid"]
    print(f"Following deployment {deployment_uid}")
    fg_get_logs = deployment_logs(clever_cli,  new_deployments[0], app_alias)
    while True:
        print("in while True")
        deployments = get_deployments(clever_cli, app_alias)
        print(f'in loop : deployements = {deployments}')
        deployment_info = [d for d in deployments if d["uuid"] == deployment_uid][0]
        print(deployment_info)
        if deployment_info["state"] != "WIP":
            break
        time.sleep(10)

    if deployment_info["state"] != "OK":
        sys.exit(f"Something went wrong in deployment {deployment_uid}")
    else:
        print(''.join(fg_get_logs.runner.stdout))
        fg_get_logs.runner.kill()



if __name__ == "__main__":
    deploy()

