clang-format-reformat-branch
============================

This script is designed to help Mozilla developers who use git with rebasing
their local changes after the tree-wide conversion planned to the Google C++
Coding Style.

This is based on the MongoDB clang_format.py script[1] explained in [2].  Many
thanks to the MongoDB project for providing the original script.

Instructions
============

After the tree-wise conversion planned to happen on Nov 30 2018 [3], you can
follow the following steps in order to rebase your local changes on top of the
reformatted tree.

  * Clone this repository somewhere on your local disk.
  * Use git remote update to pull in the reformat commit into your local git
    repository (but don't try to merge with it or rebase on top of it just
    yet, you only want to make sure the git commit exists in the git database)
  * Find out the commit SHA1s for the rewrite commit.  For example if the
    remote branch that you pulled from in the previous step is called "m-c",
    you can run this command to find the commit:

      git log --grep=1511181 m-c # grep for the bug number in the commit message
    
    Let's assume this commit is abcdef12.
  * Rebase your local branch on top of the parent of that commit (abcdef12~)
    and ensure any possible conflicts have been resolved.
  * Run the following command in the root of your mozilla-central checkout:
    
      /path/to/clang-format-reformat-branch/clang_format.py reformat-branch abcdef12 abcdef12~ m-c

    m-c here is the remote branch that is tracking mozilla-central, which is
    usually where the reformat commit has come from.  If you use this popular
    github repo [4], then this is probably called "central" in your setup.

This command first makes a few checks in the environment to ensure that everything
is right and if not shows prompts about what went wrong and after that starts
the rebase process.  As the rebase is happening, it uses `./mach clang-format`
under the hood to reformat each one of the files in your patches which have
been modified and then rebases the patch on top of the reformat commit.

If you start running this command on git branch called "foo", this command will
save its result on a new git branch called "foo-reformatted" and will check
it out when it's finished.  It will not modify the original "foo" branch in any
way, so it is not destructive.  If you're happy with the results, you may run
the following commands to make the results permanent:

  * git checkout foo
  * git reset --hard foo-reformatted # make sure the local directory is unmodified!!!


References
==========

[1] https://github.com/mongodb/mongo/blob/master/buildscripts/clang_format.py
[2] https://engineering.mongodb.com/post/succeeding-with-clangformat-part-3-persisting-the-change
[3] https://bugzilla.mozilla.org/show_bug.cgi?id=1511181
[4] https://github.com/mozilla/gecko
