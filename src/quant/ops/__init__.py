"""Operational jobs: dead-man ping, backups, restore drills, and the status page (doc 06 §6.10).

Contract: the box's own death is detected externally (healthchecks.io), never by the box; backups
are client-side encrypted (rclone crypt) and restore is drilled, not assumed; absence-of-data
alarms are first-class. These jobs are invoked by cron through the CLI and exit nonzero on any
unhandled error.
"""
