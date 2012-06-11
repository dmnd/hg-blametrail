# -*- coding: utf8 -*-
import re

import mercurial.extensions
import mercurial.commands
from mercurial.node import hex, short
from mercurial import cmdutil, nullrev
from mercurial import scmutil, patch, util, encoding


def _(s):
    return s


def blame_trail(origfn, ui, repo, *pats, **opts):
    trail_line = opts['trail']
    if trail_line == -1:
        return origfn(ui, repo, *pats, **opts)

    # have to use line_number for trail
    opts['line_number'] = True

    if opts.get('follow'):
        # --follow is deprecated and now just an alias for -f/--file
        # to mimic the behavior of Mercurial before version 1.5
        opts['file'] = True

    datefunc = ui.quiet and util.shortdate or util.datestr
    getdate = util.cachefunc(lambda x: datefunc(x[0].date()))

    if not pats:
        raise util.Abort(_('at least one filename or pattern is required'))

    hexfn = ui.debugflag and hex or short

    opmap = [('user', ' ', lambda x: ui.shortuser(x[0].user())),
             ('number', ' ', lambda x: str(x[0].rev())),
             ('changeset', ' ', lambda x: hexfn(x[0].node())),
             ('date', ' ', getdate),
             ('file', ' ', lambda x: x[0].path()),
             ('line_number', ':', lambda x: str(x[1])),
            ]

    if (not opts.get('user') and not opts.get('changeset')
        and not opts.get('date') and not opts.get('file')):
        opts['number'] = True

    linenumber = opts.get('line_number') is not None
    if linenumber and (not opts.get('changeset')) and (not opts.get('number')):
        raise util.Abort(_('at least one of -n/-c is required for -l'))

    funcmap = [(func, sep) for op, sep, func in opmap if opts.get(op)]
    funcmap[0] = (funcmap[0][0], '')  # no separator in front of first column

    def bad(x, y):
        raise util.Abort("%s: %s" % (x, y))

    ctx = scmutil.revsingle(repo, opts.get('rev'))
    m = scmutil.match(ctx, pats, opts)
    m.bad = bad
    follow = not opts.get('no_follow')
    diffopts = patch.diffopts(ui, opts, section='annotate')

    files = list(ctx.walk(m))
    assert len(files) == 1
    # todo what fails this assertion? original code assumed more than one file.

    fctx = ctx[files[0]]

    if not opts.get('text') and util.binary(fctx.data()):
        ui.write(_("%s: binary file\n") % ((pats and m.rel(abs)) or abs))
        return

    lines = fctx.annotate(follow=follow, linenumber=linenumber,
                          diffopts=diffopts)

    metadata, line_contents = lines[trail_line - 1]
    original_rev = metadata[0].rev()
    original_line = metadata[1]

    context = opts['context']
    if context != -1:
        line_s = trail_line - 1 - context
        line_e = trail_line - 1 + context + 1
        display_lines = lines[line_s:line_e]

        print "lines %i±%i:" % (trail_line, context)

        for l in display_lines:
            print "%s: %s: %s" % (l[0][0].rev(), l[0][1], l[1]),

        print

    rev = original_rev
    line = original_line

    # print the summary of the diff
    mercurial.commands.log(ui, repo, *pats, rev=[rev], follow=True, date=None)

    # now look at just the hunk with this line
    show_hunk(ui, repo, *pats, patch=True, rev=[rev], follow=True, date=None, line=line)

    ctx = scmutil.revsingle(repo, rev)
    parents = ctx.parents()
    assert len(parents) == 1
    parent = parents[0]

    ui.write("parent is %s\n" % parent)

    line = ui.prompt("Line number for next iteration", None)
    if line:
        opts['trail'] = int(line)
        opts['rev'] = str(parent)

        # recurse until we overflow the stack or run out of history :)
        # santa(parent, line, context, filename)
        blame_trail(origfn, ui, repo, *pats, **opts)


class changeset_printer(object):
    '''show changeset information when templating not requested.'''

    def __init__(self, ui, repo, patch, diffopts, buffered, line):
        self.ui = ui
        self.repo = repo
        self.buffered = buffered
        self.patch = patch
        self.diffopts = diffopts
        self.header = {}
        self.hunk = {}
        self.lastheader = None
        self.footer = None
        self.line = line

    def flush(self, rev):
        # if rev in self.header:
        #     h = self.header[rev]
        #     if h != self.lastheader:
        #         self.lastheader = h
        #         self.ui.write(h)
        #     del self.header[rev]
        if rev in self.hunk:
            self.ui.write(self.hunk[rev])
            del self.hunk[rev]
            return 1
        return 0

    def close(self):
        if self.footer:
            self.ui.write(self.footer)

    def show(self, ctx, copies=None, matchfn=None, **props):
        if self.buffered:
            self.ui.pushbuffer()
            self._show(ctx, copies, matchfn, props)
            self.hunk[ctx.rev()] = self.ui.popbuffer(labeled=True)
        else:
            self._show(ctx, copies, matchfn, props)

    def _show(self, ctx, copies, matchfn, props):
        if not matchfn:
            matchfn = self.patch

        node = ctx.node()
        diffopts = patch.diffopts(self.ui, self.diffopts)
        prev = self.repo.changelog.parents(node)[0]
        self.diff(diffopts, prev, node, match=matchfn)
        self.ui.write("\n")

    def diff(self, diffopts, node1, node2, match, changes=None):
        in_hunk = False
        line = self.line
        print_next_blank = True

        for chunk, label in patch.diffui(self.repo, node1, node2, match,
                                         changes, diffopts):
            if label == 'diff.hunk':
                if in_hunk:
                    in_hunk = False

                m = re.match(r"^@@ -(\d+),(\d+) \+(\d+),(\d+) @@$", chunk)
                lines_from = (int(m.group(1)), int(m.group(2)))
                lines_to = (int(m.group(3)), int(m.group(4)))

                if lines_to[0] <= line <= lines_to[0] + lines_to[1]:
                    in_hunk = True
                    minwidth = len(str(max(lines_to[0], lines_to[0] + lines_to[1])))
                    self.ui.write(chunk, label=label)
                    line_no = lines_from[0]

            elif in_hunk:

                # make sure any newlines came after some valid stuff
                if chunk == '\n':
                    if print_next_blank:
                        print_next_blank = False
                        self.ui.write(chunk, label=label)
                    else:
                        print "chunk: %r, label: %r" % (chunk, label)
                    continue

                if label == 'diff.inserted':
                    self.ui.write(minwidth * ' ')
                else:
                    fmt = '%' + str(minwidth) + 'i'
                    self.ui.write(fmt % line_no)
                    line_no += 1

                self.ui.write(chunk, label=label)
                print_next_blank = True


def show_hunk(ui, repo, *pats, **opts):
    matchfn = scmutil.match(repo[None], pats, opts)
    limit = cmdutil.loglimit(opts)
    count = 0

    getrenamed, endrev = None, None
    # if opts.get('copies'):
    #     if opts.get('rev'):
    #         endrev = max(scmutil.revrange(repo, opts.get('rev'))) + 1
    #     getrenamed = templatekw.getrenamedfn(repo, endrev=endrev)

    df = False
    # if opts["date"]:
    #     df = util.matchdate(opts["date"])

    branches = opts.get('branch', []) + opts.get('only_branch', [])
    opts['branch'] = [repo.lookupbranch(b) for b in branches]

    patch = scmutil.matchall(repo)

    line = opts['line']

    displayer = changeset_printer(ui, repo, patch, opts, False, line)

    def prep(ctx, fns):
        rev = ctx.rev()
        parents = [p for p in repo.changelog.parentrevs(rev)
                   if p != nullrev]
        if opts.get('no_merges') and len(parents) == 2:
            return
        if opts.get('only_merges') and len(parents) != 2:
            return
        if opts.get('branch') and ctx.branch() not in opts['branch']:
            return
        if not opts.get('hidden') and ctx.hidden():
            return
        if df and not df(ctx.date()[0]):
            return

        lower = encoding.lower
        if opts.get('user'):
            luser = lower(ctx.user())
            for k in [lower(x) for x in opts['user']]:
                if (k in luser):
                    break
            else:
                return
        if opts.get('keyword'):
            luser = lower(ctx.user())
            ldesc = lower(ctx.description())
            lfiles = lower(" ".join(ctx.files()))
            for k in [lower(x) for x in opts['keyword']]:
                if (k in luser or k in ldesc or k in lfiles):
                    break
            else:
                return

        copies = None
        if getrenamed is not None and rev:
            copies = []
            for fn in ctx.files():
                rename = getrenamed(fn, rev)
                if rename:
                    copies.append((fn, rename[0]))

        revmatchfn = None
        if opts.get('patch') or opts.get('stat'):
            if opts.get('follow') or opts.get('follow_first'):
                # note: this might be wrong when following through merges
                revmatchfn = scmutil.match(repo[None], fns, default='path')
            else:
                revmatchfn = matchfn

        displayer.show(ctx, copies=copies, matchfn=revmatchfn)

    for ctx in cmdutil.walkchangerevs(repo, matchfn, opts, prep):
        if count == limit:
            break
        if displayer.flush(ctx.rev()):
            count += 1
    displayer.close()


def uisetup(ui):
    entry = mercurial.extensions.wrapcommand(mercurial.commands.table, 'annotate',
        blame_trail)
    extra_opts = [
        ('t', 'trail', -1, ("know who's been naughty or nice")),
        ('c', 'context', 0, ("how much context to show around hunks"))
    ]
    entry[1].extend(extra_opts)
