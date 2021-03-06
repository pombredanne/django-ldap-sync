import ldap
from ldap.controls import SimplePagedResultsControl
import logging

from django.conf import settings
from django.core.management.base import NoArgsCommand
from django.contrib.auth.models import User
from django.contrib.auth.models import Group
from django.contrib.auth.models import SiteProfileNotAvailable


log = logging.getLogger(__name__)


class Command(NoArgsCommand):
    help = "Synchronize users and groups with an authoritative LDAP server"

    def handle_noargs(self, **options):
        ldap_groups = self.get_ldap_groups()
        ldap_users = self.get_ldap_users()

        self.sync_ldap_groups(ldap_groups)
        self.sync_ldap_users(ldap_users, ldap_groups)

    def get_ldap_users(self):
        """
        Retrieve users from target LDAP server.
        """
        filterstr = "(&(objectCategory=person)(objectClass=user))"
        attrlist = ['mailNickname', 'mail', 'givenName', 'sn', 'ipPhone', ]
        page_size = 100
        users = []

        try:
            l = ldap.initialize(settings.AUTH_LDAP_URI)
            l.set_option(ldap.OPT_REFERRALS, 0)
            l.protocol_version = ldap.VERSION3
            l.simple_bind_s(settings.AUTH_LDAP_BASE_USER, settings.AUTH_LDAP_BASE_PASS)
        except ldap.LDAPError, e:
            log.error("Cannot connect to LDAP server: %s" % str(e))
            return None

        lc = SimplePagedResultsControl(ldap.LDAP_CONTROL_PAGE_OID, True, (page_size, ''))

        while True:
            msgid = l.search_ext(settings.AUTH_LDAP_BASE, ldap.SCOPE_SUBTREE, filterstr, attrlist, serverctrls=[lc])
            rtype, rdata, rmsgid, serverctrls = l.result3(msgid)
            for result in rdata:
                users.append(result)
            pctrls = [
                c
                for c in serverctrls
                if c.controlType == ldap.LDAP_CONTROL_PAGE_OID
            ]
            if pctrls:
                est, cookie = pctrls[0].controlValue
                if cookie:
                    lc.controlValue = (page_size, cookie)
                else:
                    break
            else:
                log.error("Server ignores RFC 2696 control")
                break

        l.unbind_s()

        return users

    def sync_ldap_users(self, ldap_users, ldap_groups):
        """
        Synchronize users with local user database.
        """
        log.info("Synchronizing %d users" % len(users))

        for ldap_user in ldap_users:
            try:
                username = ldap_user[1]['mailNickname'][0]
            except:
                pass
            else:
                try:
                    first_name = ldap_user[1]['givenName'][0]
                except:
                    first_name = ''
                try:
                    last_name = ldap_user[1]['sn'][0]
                except:
                    last_name = ''
                try:
                    id_num = ldap_user[1]['ipPhone'][0]
                except:
                    id_num = ''
                try:
                    email = ldap_user[1]['mail'][0]
                except:
                    email = ''

                try:
                    user = User.objects.get(username=username)
                except User.DoesNotExist:
                    user = User.objects.create_user(username, email)
                    user.first_name = first_name
                    user.last_name = last_name
                    log.info("User '%s' created" % username)
                else:
                    if not user.first_name == first_name.decode('utf-8'):
                        user.first_name = first_name
                        log.info("User '%s' first name updated" % username)
                    if not user.last_name == last_name.decode('utf-8'):
                        user.last_name = last_name
                        log.info("User '%s' last name updated" % username)
                    if not user.email == email:
                        user.email = email
                        log.info("User '%s' email updated" % username)
                user.save()

                try:
                    profile = user.get_profile()
                except (ObjectDoesNotExist, SiteProfileNotAvailable):
                    profile = UserProfile(user=user, id_num=id_num)
                    log.info("User '%s' profile created" % username)
                else:
                    if not profile.id_num == id_num:
                        profile.id_num = id_num
                        log.info("User '%s' id number updated" % username)
                try:
                    profile.save()
                except:
                    log.error("Duplicate ID '%s' encountered for '%s'" % (id_num, username))

        log.info("Users are synchronized")

    def get_ldap_groups(self):
        """
        Retrieve groups from target LDAP server.
        """
        scope = AUTH_LDAP_SCOPE
        filter = "(&(objectclass=posixGroup))"
        values = ['cn', 'memberUid']
        l = ldap.open(AUTH_LDAP_SERVER)
        l.protocol_version = ldap.VERSION3
        l.simple_bind_s(AUTH_LDAP_BASE_USER,AUTH_LDAP_BASE_PASS)
        result_id = l.search('ou=Groups,'+AUTH_LDAP_BASE, scope, filter, values)
        result_type, result_data = l.result(result_id, 1)
        l.unbind()
        return result_data

    def sync_ldap_groups(self, ldap_groups):
        """
        Synchronize groups with local group database.
        """
        for ldap_group in ldap_groups:
            try:
                group_name = ldap_group[1]['cn'][0]
            except:
                pass
            else:
                try:
                    group = Group.objects.get(name=group_name)
                except Group.DoesNotExist:
                    group = Group(name=group_name)
                    group.save()
                    log.debug("Group '%s' created." % group_name)
        log.info("Groups are synchronized")
