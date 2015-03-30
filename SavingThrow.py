#!/usr/bin/python
"""SavingThrow

Identify or remove files known to be involved in Adware infection,
based on curated lists of associated files.

Copyright (C) 2015 Shea G Craig <shea.craig@da.org>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""

# Import ALL the modules!
import argparse
import glob
import os
import re
import shutil
import sys
import syslog
import time
import urllib2


# Add any URL's to nefarious file lists here:
NEFARIOUS_FILE_SOURCES = []
# File format is one path per line.
# Files to look for may include globbing characters
# Default is to at least use Apple's files from:
# https://support.apple.com/en-us/ht203987
NEFARIOUS_FILE_SOURCES.append('https://gist.githubusercontent.com/sheagcraig/5c76604f823d45792952/raw/8e8eaa9f69905265912ccc615949505558ff40f6/AppleAdwareList')

CACHE = '/Library/Application Support/SavingThrow'
if not os.path.exists(CACHE):
    os.mkdir(CACHE)


class Logger():
    """Simple logging class."""
    def __init__(self, verbose=False):
        self.verbose = verbose

    def log(self, message, log_level=syslog.LOG_ALERT):
        """Log to the syslog, and if verbose, also to stdout."""
        syslog.syslog(log_level, message)
        if self.verbose:
            print(message)

    def vlog(self, message, log_level=syslog.LOG_ALERT):
        """Log to the syslog, and to stdout."""
        syslog.syslog(log_level, message)
        print(message)

# Make our global logger.
logger = Logger()

def build_argparser():
    """Create our argument parser."""
    description = ("Modular Adware Extension Attribute and "
                   "Removal Script. Call with no arguments to run as "
                   "an extension attribute, or with --remove or "
                   "--quarantine to operate as a cleanup tool.")
    epilog = ("Roll to save against paralyzation, lest the Gelatinous "
              "Cube anesthetizes, and ultimately, digests you.")
    parser = argparse.ArgumentParser(description=description, epilog=epilog)
    help = ("Accepts all passed positional arguments (or none) to "
            "allow Casper script usage.")
    parser.add_argument('jamf-arguments', nargs='*', help=help)
    parser.add_argument('-v', '--verbose', action="store_true",
                        help="Print to stdout as well as syslog.")
    mode_parser = parser.add_mutually_exclusive_group()
    mode_parser.add_argument(
        "-s", "--stdout", help="Print standard report.", action='store_true')
    mode_parser.add_argument(
        "-r", "--remove", help="Remove offending files.", action='store_true')
    mode_parser.add_argument(
        "-q", "--quarantine", help="Move offending files to quarantine "
        "location.", action='store_true')

    return parser


def get_projectX_files():
    """Return a set of vSearch agent-related LaunchD configuration
    files.

    This adware seems to have a different name each time it pops up.
    Apple's solution is too broad. We look at the files Apple suggests,
    but then also search within to see if they are calling a known
    binary file, "agent.app/Contents/MacOS/agent".

    """
    projectx_files = {
        '/Library/LaunchAgents/com.*.agent.plist',
        '/Library/LaunchDaemons/com.*.helper.plist',
        '/Library/LaunchDaemons/com.*.daemon.plist'}

    projectx_candidates = {match for filename in projectx_files for match in
                    glob.glob(filename)}

    agent_regex = re.compile('.*/Library/Application Support/(.*)/Agent/agent.app/Contents/MacOS/agent')
    result = set()

    for candidate in projectx_candidates:
        with open(candidate, 'r') as candidate_file:
            launchd_job = candidate_file.read()

        if re.search(agent_regex, launchd_job):
            result.add(candidate)
            # If we find a Launch[Agent|Daemon] that has ProgramArguments
            # which runs "agent", find the unique name for this instance.
            # We can then use it to find the Application Support folder.
            obfuscated_name = re.search(agent_regex, launchd_job).group(1)
            result.add('/Library/Application Support/%s' % obfuscated_name)

    return result


def load_adware_description_files(sources):
    """Given a list of URLs to adware description files, attempt to
    download, parse, and generate a master set of targeted files.

    Returns a set of nefarious files.

    """
    known_adware = set()
    for source in sources:
        try:
            logger.log("Attempting to update Adware list: %s" % source)
            adware_list = urllib2.urlopen(source).read()

            # Update our cached copy
            try:
                with open(os.path.join(CACHE, os.path.basename(source)), 'w') as f:
                    f.write(adware_list)
            except IOError as e:
                if e[0] == 13:
                    print("Please run as root!")
                    sys.exit(13)
                else:
                    raise e

        except urllib2.URLError as e:
            # Use the cached copy if it exists.
            logger.log("Update failed: %s. Looking for cached copy" % e.message)
            try:
                with open(os.path.join(CACHE, os.path.basename(source)), 'r') as f:
                    adware_list = f.read()
            except IOError as e:
                logger.log("Error: No cached copy of %s or other error %s" %
                      (source, e.message))

        known_adware.update({file for file in adware_list.split('\n')})

    return known_adware


def remove(files):
    """Delete identified files and directories."""
    for item in files:
        try:
            if os.path.isdir(item):
                shutil.rmtree(item)
            elif os.path.isfile(item):
                os.remove(item)
            logger.log("Removed adware file:  %s" % item)
        except OSError as e:
            logger.log("Failed to remove adware file:  %s, %s" % (item, e))


def quarantine(files):
    """Move all identified files to a timestamped folder in our cache.

    """
    # Let's not bother if the list is empty.
    if files:
        backup_dir = os.path.join(CACHE, time.strftime("%Y%m%d-%H%M%S"))
        os.mkdir(backup_dir)

    for item in files:
        try:
            shutil.move(item, backup_dir)
            logger.log("Quarantined adware file:  %s" % item)
        except OSError as e:
            logger.log("Failed to quarantine adware file:  %s, %s" %
                       (item, e))


def report_to_stdout(files):
    """Report back on identified files."""
    result = 'Adware files found: %s\n' % len(files)
    if files:
        for item in enumerate(files):
            result += "%d: %s\n" % item

    logger.vlog(result)


def extension_attribute(files):
    """Report back on identified files in a Casper extension attribute
    format.

    """
    result = '<result>'
    if files:
        result += 'True\n'
        for item in enumerate(files):
            result += "%d: %s\n" % item
    else:
        result += 'False'

    result += '</result>'

    logger.vlog(result)


def unload_and_disable_launchd_jobs(files):
    """Given an iterable of paths, attempt to unload and disable any
    launchd configuration files.

    """
    # Find system-level LaunchD config files.
    conf_locs = {'/Library/LaunchAgents',
                 '/Library/LaunchDaemons',
                 '/System/Library/LaunchAgents',
                 '/System/Library/LaunchDaemons'}

    # Add valid per-user config locations.
    for user_home in os.listdir('/Users'):
        candidate_launchd_loc = os.path.join('/Users', user_home, 'Library/LaunchAgents')
        if os.path.exists(candidate_launchd_loc):
            conf_locs.add(candidate_launchd_loc)
    launchd_config_files = {file for file in files for conf_loc in conf_locs if file.find(conf_loc) == 0}


def main():
    """Manage arguments and coordinate our saving throw."""
    # Handle command line arguments
    parser = build_argparser()
    args = parser.parse_args()

    if args.verbose:
        logger.verbose = True

    known_adware = set()
    known_adware.update(load_adware_description_files(
        NEFARIOUS_FILE_SOURCES))

    # Look for projectX files.
    known_adware.update(get_projectX_files())

    # Build a set of adware files that are on the drive.
    found_adware = {match for filename in known_adware for match in
                    glob.glob(filename)}

    # Is this an EA or a script execution?
    if args.remove:
        remove(found_adware)
    elif args.quarantine:
        quarantine(found_adware)
    elif args.stdout:
        report_to_stdout(found_adware)
    else:
        extension_attribute(found_adware)


if __name__ == '__main__':
    main()
