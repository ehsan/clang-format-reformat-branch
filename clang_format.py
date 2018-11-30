#!/usr/bin/env python
from __future__ import print_function, absolute_import

import difflib
import glob
import os
import re
import shutil
import string
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib2
from distutils import spawn  # pylint: disable=no-name-in-module
from optparse import OptionParser
from multiprocessing import cpu_count

# Get relative imports to work when the package is not installed on the PYTHONPATH.
if __name__ == "__main__" and __package__ is None:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(os.path.realpath(__file__)))))

import git  # pylint: disable=wrong-import-position
#from buildscripts.linter import parallel  # pylint: disable=wrong-import-position

##############################################################################
class ClangFormat(object):
    """ClangFormat class."""

    def __init__(self):  # pylint: disable=too-many-branches
        """Initialize ClangFormat."""
        self.path = None
        if not os.path.isfile("mach"):
            print("WARNING: Could not find mach")
            raise Exception("mach not found")
        self.path = os.path.abspath("mach")

        self.print_lock = threading.Lock()

    def format(self, file_name):
        # Update the file with clang-format
        formatted = not subprocess.call([self.path, "clang-format", "-p", file_name])

        return formatted


FILES_RE = re.compile('\\.(h|hpp|ipp|cpp|js)$')


def is_interesting_file(file_name):
    """Return true if this file should be checked."""
    return FILES_RE.search(file_name)


def get_list_from_lines(lines):
    """Convert a string containing a series of lines into a list of strings."""
    return [line.rstrip() for line in lines.splitlines()]


def reformat_branch(  # pylint: disable=too-many-branches,too-many-locals,too-many-statements
        clang_format, commit_prior_to_reformat, commit_after_reformat, target_branch):
    """Reformat a branch made before a clang-format run."""
    clang_format = ClangFormat()

    if os.getcwd() != git.get_base_dir():
        raise ValueError("reformat-branch must be run from the repo root")

    repo = git.Repo(git.get_base_dir())

    commit_prior_to_reformat = repo.git_rev_parse([commit_prior_to_reformat])
    commit_after_reformat = repo.git_rev_parse([commit_after_reformat])

    # Validate that user passes valid commits
    if not repo.is_commit(commit_prior_to_reformat):
        raise ValueError("Commit Prior to Reformat '%s' is not a valid commit in this repo" %
                         commit_prior_to_reformat)

    if not repo.is_commit(commit_after_reformat):
        raise ValueError(
            "Commit After Reformat '%s' is not a valid commit in this repo" % commit_after_reformat)

    if not repo.is_ancestor(commit_prior_to_reformat, commit_after_reformat):
        raise ValueError(("Commit Prior to Reformat '%s' is not a valid ancestor of Commit After" +
                          " Reformat '%s' in this repo") % (commit_prior_to_reformat,
                                                            commit_after_reformat))

    # Validate the user is on a local branch that has the right merge base
    if repo.is_detached():
        raise ValueError("You must not run this script in a detached HEAD state")

    # Validate the user has no pending changes
    if repo.is_working_tree_dirty():
        raise ValueError(
            "Your working tree has pending changes. You must have a clean working tree before proceeding."
        )

    merge_base = repo.get_merge_base(commit_prior_to_reformat)

    if not merge_base == commit_prior_to_reformat:
        raise ValueError(
            "Please rebase to '%s' and resolve all conflicts before running this script" %
            (commit_prior_to_reformat))

    # We assume the target branch is master, it could be a different branch if needed for testing
    merge_base = repo.get_merge_base(target_branch)

    if not merge_base == commit_prior_to_reformat:
        raise ValueError(
            "This branch appears to already have advanced too far through the merge process")

    # Everything looks good so lets start going through all the commits
    branch_name = repo.get_branch_name()
    new_branch = "%s-reformatted" % branch_name

    if repo.does_branch_exist(new_branch):
        raise ValueError(
            "The branch '%s' already exists. Please delete the branch '%s', or rename the current branch."
            % (new_branch, new_branch))

    commits = get_list_from_lines(
        repo.git_log(["--reverse", "--pretty=format:%H",
                      "%s..HEAD" % commit_prior_to_reformat]))

    previous_commit_base = commit_after_reformat

    files_match = re.compile('\\.(h|cpp|c|cc)$')

    # Go through all the commits the user made on the local branch and migrate to a new branch
    # that is based on post_reformat commits instead
    for commit_hash in commits:
        repo.git_checkout(["--quiet", commit_hash])

        deleted_files = []

        # Format each of the files by checking out just a single commit from the user's branch
        commit_files = get_list_from_lines(repo.git_diff(["HEAD~", "--name-only"]))

        for commit_file in commit_files:

            # Format each file needed if it was not deleted
            if not os.path.exists(commit_file):
                print("Skipping file '%s' since it has been deleted in commit '%s'" % (commit_file,
                                                                                       commit_hash))
                deleted_files.append(commit_file)
                continue

            if files_match.search(commit_file):
                clang_format.format(commit_file)
            else:
                print("Skipping file '%s' since it is not a file clang_format should format" %
                      commit_file)

        # Check if anything needed reformatting, and if so amend the commit
        if not repo.is_working_tree_dirty():
            print("Commit %s needed no reformatting" % commit_hash)
        else:
            repo.git_commit(["--all", "--amend", "--no-edit"])

        # Rebase our new commit on top the post-reformat commit
        previous_commit = repo.git_rev_parse(["HEAD"])

        # Checkout the new branch with the reformatted commits
        # Note: we will not name as a branch until we are done with all commits on the local branch
        repo.git_checkout(["--quiet", previous_commit_base])

        # Copy each file from the reformatted commit on top of the post reformat
        diff_files = get_list_from_lines(
            repo.git_diff(["%s~..%s" % (previous_commit, previous_commit), "--name-only"]))

        for diff_file in diff_files:
            # If the file was deleted in the commit we are reformatting, we need to delete it again
            if diff_file in deleted_files:
                repo.git_rm([diff_file])
                continue

            # The file has been added or modified, continue as normal
            file_contents = repo.git_show(["%s:%s" % (previous_commit, diff_file)])

            root_dir = os.path.dirname(diff_file)
            if root_dir and not os.path.exists(root_dir):
                os.makedirs(root_dir)

            with open(diff_file, "w+") as new_file:
                new_file.write(file_contents)

            repo.git_add([diff_file])

        # Create a new commit onto clang-formatted branch
        repo.git_commit(["--reuse-message=%s" % previous_commit])

        previous_commit_base = repo.git_rev_parse(["HEAD"])

    # Create a new branch to mark the hashes we have been using
    repo.git_checkout(["-b", new_branch])

    print("reformat-branch is done running.\n")
    print("A copy of your branch has been made named '%s', and formatted with clang-format.\n" %
          new_branch)
    print("The original branch has been left unchanged.")
    print("The next step is to rebase the new branch on '%s'." %
          target_branch)


def usage():
    """Print usage."""
    print(
        "clang-format.py supports 1 command [reformat-branch]."
    )
    print("\nformat-my <origin branch>")
    print("   <origin branch>  - upstream branch to compare against")


def main():
    """Execute Main entry point."""
    parser = OptionParser()
    parser.add_option("-c", "--clang-format", type="string", dest="clang_format")

    (options, args) = parser.parse_args(args=sys.argv)

    if len(args) > 1:
        command = args[1]

        if command == "reformat-branch":

            if len(args) < 4:
                print(
                    "ERROR: reformat-branch takes three parameters: commit_prior_to_reformat commit_after_reformat target_branch"
                )
                return

            reformat_branch(options.clang_format, args[2], args[3], args[4])
        else:
            usage()
    else:
        usage()


if __name__ == "__main__":
    main()
