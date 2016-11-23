# Copyright 2014 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import datetime
import re

import ply.yacc as yacc
from sqlalchemy.sql.expression import and_, or_, not_, select, func

import boartty.db
import boartty.search
from boartty.search.tokenizer import tokens  # NOQA

def age_to_delta(delta, unit):
    if unit in ['seconds', 'second', 'sec', 's']:
        pass
    elif unit in ['minutes', 'minute', 'min', 'm']:
        delta = delta * 60
    elif unit in ['hours', 'hour', 'hr', 'h']:
        delta = delta * 60 * 60
    elif unit in ['days', 'day', 'd']:
        delta = delta * 60 * 60 * 24
    elif unit in ['weeks', 'week', 'w']:
        delta = delta * 60 * 60 * 24 * 7
    elif unit in ['months', 'month', 'mon']:
        delta = delta * 60 * 60 * 24 * 30
    elif unit in ['years', 'year', 'y']:
        delta = delta * 60 * 60 * 24 * 365
    return delta

def SearchParser():
    precedence = (  # NOQA
        ('left', 'NOT', 'NEG'),
    )

    def p_terms(p):
        '''expression : list_expr
                      | paren_expr
                      | boolean_expr
                      | negative_expr
                      | term'''
        p[0] = p[1]

    def p_list_expr(p):
        '''list_expr : expression expression'''
        p[0] = and_(p[1], p[2])

    def p_paren_expr(p):
        '''paren_expr : LPAREN expression RPAREN'''
        p[0] = p[2]

    def p_boolean_expr(p):
        '''boolean_expr : expression AND expression
                        | expression OR expression'''
        if p[2].lower() == 'and':
            p[0] = and_(p[1], p[3])
        elif p[2].lower() == 'or':
            p[0] = or_(p[1], p[3])
        else:
            raise boartty.search.SearchSyntaxError("Boolean %s not recognized" % p[2])

    def p_negative_expr(p):
        '''negative_expr : NOT expression
                         | NEG expression'''
        p[0] = not_(p[2])

    def p_term(p):
        '''term : age_term
                | recentlyseen_term
                | story_term
                | owner_term
                | reviewer_term
                | commit_term
                | project_term
                | projects_term
                | project_key_term
                | branch_term
                | tag_term
                | ref_term
                | label_term
                | message_term
                | comment_term
                | has_term
                | is_term
                | status_term
                | file_term
                | limit_term
                | op_term'''
        p[0] = p[1]

    def p_string(p):
        '''string : SSTRING
                  | DSTRING
                  | USTRING'''
        p[0] = p[1]

    def p_age_term(p):
        '''age_term : OP_AGE NUMBER string'''
        now = datetime.datetime.utcnow()
        delta = p[2]
        unit = p[3]
        delta = age_to_delta(delta, unit)
        p[0] = boartty.db.story_table.c.updated < (now-datetime.timedelta(seconds=delta))

    def p_recentlyseen_term(p):
        '''recentlyseen_term : OP_RECENTLYSEEN NUMBER string'''
        # A boartty extension
        now = datetime.datetime.utcnow()
        delta = p[2]
        unit = p[3]
        delta = age_to_delta(delta, unit)
        s = select([func.datetime(func.max(boartty.db.story_table.c.last_seen), '-%s seconds' % delta)],
                   correlate=False)
        p[0] = boartty.db.story_table.c.last_seen >= s

    def p_story_term(p):
        '''story_term : OP_STORY NUMBER'''
        p[0] = boartty.db.story_table.c.id == p[2]

    def p_owner_term(p):
        '''owner_term : OP_OWNER string'''
        if p[2] == 'self':
            username = p.parser.username
            p[0] = boartty.db.user_table.c.username == username
        else:
            p[0] = or_(boartty.db.user_table.c.username == p[2],
                       boartty.db.user_table.c.email == p[2],
                       boartty.db.user_table.c.name == p[2])

    def p_reviewer_term(p):
        '''reviewer_term : OP_REVIEWER string
                         | OP_REVIEWER NUMBER'''
        filters = []
        filters.append(boartty.db.approval_table.c.story_key == boartty.db.story_table.c.key)
        filters.append(boartty.db.approval_table.c.user_key == boartty.db.user_table.c.key)
        try:
            number = int(p[2])
        except:
            number = None
        if number is not None:
            filters.append(boartty.db.user_table.c.id == number)
        elif p[2] == 'self':
            username = p.parser.username
            filters.append(boartty.db.user_table.c.username == username)
        else:
            filters.append(or_(boartty.db.user_table.c.username == p[2],
                               boartty.db.user_table.c.email == p[2],
                               boartty.db.user_table.c.name == p[2]))
        s = select([boartty.db.story_table.c.key], correlate=False).where(and_(*filters))
        p[0] = boartty.db.story_table.c.key.in_(s)

    def p_commit_term(p):
        '''commit_term : OP_COMMIT string'''
        filters = []
        filters.append(boartty.db.revision_table.c.story_key == boartty.db.story_table.c.key)
        filters.append(boartty.db.revision_table.c.commit == p[2])
        s = select([boartty.db.story_table.c.key], correlate=False).where(and_(*filters))
        p[0] = boartty.db.story_table.c.key.in_(s)

    def p_project_term(p):
        '''project_term : OP_PROJECT string'''
        if p[2].startswith('^'):
            p[0] = func.matches(p[2], boartty.db.project_table.c.name)
        else:
            p[0] = boartty.db.project_table.c.name == p[2]

    def p_projects_term(p):
        '''projects_term : OP_PROJECTS string'''
        p[0] = boartty.db.project_table.c.name.like('%s%%' % p[2])

    def p_project_key_term(p):
        '''project_key_term : OP_PROJECT_KEY NUMBER'''
        #p[0] = boartty.db.story_table.c.project_key == p[2]
        filters = []
        filters.append(boartty.db.task_table.c.story_key == boartty.db.story_table.c.key)
        filters.append(boartty.db.task_table.c.project_key == p[2])
        s = select([boartty.db.story_table.c.key], correlate=False).where(and_(*filters))
        p[0] = boartty.db.story_table.c.key.in_(s)

    def p_branch_term(p):
        '''branch_term : OP_BRANCH string'''
        if p[2].startswith('^'):
            p[0] = func.matches(p[2], boartty.db.story_table.c.branch)
        else:
            p[0] = boartty.db.story_table.c.branch == p[2]

    def p_tag_term(p):
        '''tag_term : OP_TAG string'''
        if p[2].startswith('^'):
            p[0] = func.matches(p[2], boartty.db.tag_table.c.name)
        else:
            p[0] = boartty.db.tag_table.c.name == p[2]

    def p_ref_term(p):
        '''ref_term : OP_REF string'''
        if p[2].startswith('^'):
            p[0] = func.matches(p[2], 'refs/heads/'+boartty.db.story_table.c.branch)
        else:
            p[0] = boartty.db.story_table.c.branch == p[2][len('refs/heads/'):]

    label_re = re.compile(r'(?P<label>[a-zA-Z0-9_-]+([a-zA-Z]|((?<![-+])[0-9])))'
                          r'(?P<operator>[<>]?=?)(?P<value>[-+]?[0-9]+)'
                          r'($|,(user=)?(?P<user>\S+))')

    def p_label_term(p):
        '''label_term : OP_LABEL string'''
        args = label_re.match(p[2])
        label = args.group('label')
        op = args.group('operator') or '='
        value = int(args.group('value'))
        user = args.group('user')

        filters = []
        filters.append(boartty.db.approval_table.c.story_key == boartty.db.story_table.c.key)
        filters.append(boartty.db.approval_table.c.category == label)
        if op == '=':
            filters.append(boartty.db.approval_table.c.value == value)
        elif op == '>=':
            filters.append(boartty.db.approval_table.c.value >= value)
        elif op == '<=':
            filters.append(boartty.db.approval_table.c.value <= value)
        if user is not None:
            filters.append(boartty.db.approval_table.c.user_key == boartty.db.user_table.c.key)
            if user == 'self':
                filters.append(boartty.db.user_table.c.username == p.parser.username)
            else:
                filters.append(
                    or_(boartty.db.user_table.c.username == user,
                        boartty.db.user_table.c.email == user,
                        boartty.db.user_table.c.name == user))
        s = select([boartty.db.story_table.c.key], correlate=False).where(and_(*filters))
        p[0] = boartty.db.story_table.c.key.in_(s)

    def p_message_term(p):
        '''message_term : OP_MESSAGE string'''
        filters = []
        filters.append(boartty.db.revision_table.c.story_key == boartty.db.story_table.c.key)
        filters.append(boartty.db.revision_table.c.message.like('%%%s%%' % p[2]))
        s = select([boartty.db.story_table.c.key], correlate=False).where(and_(*filters))
        p[0] = boartty.db.story_table.c.key.in_(s)

    def p_comment_term(p):
        '''comment_term : OP_COMMENT string'''
        filters = []
        filters.append(boartty.db.revision_table.c.story_key == boartty.db.story_table.c.key)
        filters.append(boartty.db.revision_table.c.message == p[2])
        revision_select = select([boartty.db.story_table.c.key], correlate=False).where(and_(*filters))
        filters = []
        filters.append(boartty.db.revision_table.c.story_key == boartty.db.story_table.c.key)
        filters.append(boartty.db.comment_table.c.revision_key == boartty.db.revision_table.c.key)
        filters.append(boartty.db.comment_table.c.message == p[2])
        comment_select = select([boartty.db.story_table.c.key], correlate=False).where(and_(*filters))
        p[0] = or_(boartty.db.story_table.c.key.in_(comment_select),
                   boartty.db.story_table.c.key.in_(revision_select))

    def p_has_term(p):
        '''has_term : OP_HAS string'''
        #TODO: implement star
        if p[2] == 'draft':
            filters = []
            filters.append(boartty.db.revision_table.c.story_key == boartty.db.story_table.c.key)
            filters.append(boartty.db.message_table.c.revision_key == boartty.db.revision_table.c.key)
            filters.append(boartty.db.message_table.c.draft == True)
            s = select([boartty.db.story_table.c.key], correlate=False).where(and_(*filters))
            p[0] = boartty.db.story_table.c.key.in_(s)
        else:
            raise boartty.search.SearchSyntaxError('Syntax error: has:%s is not supported' % p[2])

    def p_is_term(p):
        '''is_term : OP_IS string'''
        #TODO: implement draft
        username = p.parser.username
        if p[2] == 'reviewed':
            filters = []
            filters.append(boartty.db.approval_table.c.story_key == boartty.db.story_table.c.key)
            filters.append(boartty.db.approval_table.c.value != 0)
            s = select([boartty.db.story_table.c.key], correlate=False).where(and_(*filters))
            p[0] = boartty.db.story_table.c.key.in_(s)
        elif p[2] == 'open':
            p[0] = boartty.db.story_table.c.status.notin_(['MERGED', 'ABANDONED'])
        elif p[2] == 'closed':
            p[0] = boartty.db.story_table.c.status.in_(['MERGED', 'ABANDONED'])
        elif p[2] == 'submitted':
            p[0] = boartty.db.story_table.c.status == 'SUBMITTED'
        elif p[2] == 'merged':
            p[0] = boartty.db.story_table.c.status == 'MERGED'
        elif p[2] == 'abandoned':
            p[0] = boartty.db.story_table.c.status == 'ABANDONED'
        elif p[2] == 'owner':
            p[0] = boartty.db.user_table.c.username == username
        elif p[2] == 'starred':
            p[0] = boartty.db.story_table.c.starred == True
        elif p[2] == 'held':
            # A boartty extension
            p[0] = boartty.db.story_table.c.held == True
        elif p[2] == 'reviewer':
            filters = []
            filters.append(boartty.db.approval_table.c.story_key == boartty.db.story_table.c.key)
            filters.append(boartty.db.approval_table.c.user_key == boartty.db.user_table.c.key)
            filters.append(boartty.db.user_table.c.username == username)
            s = select([boartty.db.story_table.c.key], correlate=False).where(and_(*filters))
            p[0] = boartty.db.story_table.c.key.in_(s)
        elif p[2] == 'watched':
            p[0] = boartty.db.project_table.c.subscribed == True
        else:
            raise boartty.search.SearchSyntaxError('Syntax error: is:%s is not supported' % p[2])

    def p_file_term(p):
        '''file_term : OP_FILE string'''
        if p[2].startswith('^'):
            p[0] = and_(or_(func.matches(p[2], boartty.db.file_table.c.path),
                            func.matches(p[2], boartty.db.file_table.c.old_path)),
                        boartty.db.file_table.c.status is not None)
        else:
            p[0] = and_(or_(boartty.db.file_table.c.path == p[2],
                            boartty.db.file_table.c.old_path == p[2]),
                        boartty.db.file_table.c.status is not None)

    def p_status_term(p):
        '''status_term : OP_STATUS string'''
        if p[2] == 'open':
            p[0] = boartty.db.story_table.c.status.notin_(['MERGED', 'ABANDONED'])
        elif p[2] == 'closed':
            p[0] = boartty.db.story_table.c.status.in_(['MERGED', 'ABANDONED'])
        else:
            p[0] = boartty.db.story_table.c.status == p[2]

    def p_limit_term(p):
        '''limit_term : OP_LIMIT NUMBER'''
        # TODO: Implement this.  The sqlalchemy limit call needs to be
        # applied to the query operation and so can not be returned as
        # part of the production here.  The information would need to
        # be returned out-of-band.  In the mean time, since limits are
        # not as important in boartty, make this a no-op for now so
        # that it does not produce a syntax error.
        p[0] = (True == True)

    def p_op_term(p):
        'op_term : OP'
        raise SyntaxError()

    def p_error(p):
        if p:
            raise boartty.search.SearchSyntaxError('Syntax error at "%s" in search string "%s" (col %s)' % (
                    p.lexer.lexdata[p.lexpos:], p.lexer.lexdata, p.lexpos))
        else:
            raise boartty.search.SearchSyntaxError('Syntax error: EOF in search string')

    return yacc.yacc(debug=0, write_tables=0)
