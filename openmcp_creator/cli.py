import argparse
import getpass
import json
import uuid

import uvicorn

from openmcp.config import Settings

from .app import create_app, public_job
from .models import CreateRequest, origin
from .settings import CreatorSettings
from .store import CreatorStore
from .vault import Vault


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create paid OpenMCP tools from URLs")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Run the durable worker and paid adapter host")
    serve.add_argument("--port", type=int, default=9002)
    create = commands.add_parser("create", help="Queue a URL for investigation")
    create.add_argument("url")
    create.add_argument("--goal", default="Expose useful data from this source")
    create.add_argument("--price-cents", type=int, required=True)
    create.add_argument("--wallet", default="openmcp")
    create.add_argument("--allow-origin", action="append", default=[])
    create.add_argument("--key", default=None)
    create.add_argument("--max-steps", type=int, default=20)
    status = commands.add_parser("status", help="Inspect jobs and pending signup actions")
    status.add_argument("job_id", nargs="?")
    resume = commands.add_parser("resume", help="Resume after credentials or account setup")
    resume.add_argument("job_id")
    resume.add_argument("--approve-action", action="store_true")
    resume.add_argument(
        "--regenerate", action="store_true", help="Discard a failed adapter and investigate again"
    )
    resume.add_argument(
        "--note",
        default="",
        help="Account setup progress or corrected requirements; never credentials",
    )
    secret = commands.add_parser("secret", help="Store a job credential using a hidden prompt")
    secret.add_argument("job_id")
    secret.add_argument("name")
    secret.add_argument("--origin", required=True)
    args = parser.parse_args(argv)
    settings, creator_settings = Settings(), CreatorSettings()
    store = CreatorStore(settings.creator_database)
    if args.command == "serve":
        from urllib.parse import urlsplit

        if (urlsplit(creator_settings.base_url).port or 80) != args.port:
            parser.error("--port must match OPENMCP_CREATOR_BASE_URL")
        uvicorn.run(
            create_app(settings, creator_settings), host="127.0.0.1", port=args.port, workers=1
        )
        return
    if args.command == "create":
        if args.wallet not in settings.addresses():
            parser.error("Unknown receiving wallet")
        result = store.submit(
            CreateRequest(
                url=args.url,
                goal=args.goal,
                price_cents=args.price_cents,
                wallet=args.wallet,
                allowed_origins=args.allow_origin,
                idempotency_key=args.key or uuid.uuid4().hex,
                max_steps=args.max_steps,
            )
        )
    elif args.command == "status":
        result = store.get(args.job_id) if args.job_id else None
        if result is None:
            print(json.dumps([public_job(j) for j in store.list()], indent=2))
            return
    elif args.command == "resume":
        result = store.resume(
            args.job_id,
            approve_action=args.approve_action,
            regenerate=args.regenerate,
            note=args.note[:4000],
        )
    else:
        import re

        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", args.name):
            parser.error("Secret name must be lowercase letters, digits, underscores or hyphens")
        job = store.get(args.job_id)
        if origin(args.origin) not in CreateRequest.model_validate(job["request"]).origins:
            parser.error("Credential origin must be authorized by the job")
        if job["state"] == "running":
            parser.error("Wait for the running job before updating its credentials")
        value = getpass.getpass("Credential (hidden): ")
        if not value:
            parser.error("Credential cannot be empty")
        Vault(settings.creator_database.parent / "creator").put(
            args.job_id, args.name, value, args.origin
        )
        print("Credential saved. Resume the job when account setup is complete.")
        return
    print(json.dumps(public_job(result), indent=2))


if __name__ == "__main__":
    main()
