import json, requests, os, copy, sys
from pysys.basetest import BaseTest
from pysys.constants import PROJECT, BACKGROUND
from ethsys.utils.process import Processes
from ethsys.utils.properties import Properties


class EthereumTest(BaseTest):
    ONE_GIGA = 1000000000000000000

    def __init__(self, descriptor, outsubdir, runner):
        """Call the parent constructor but set the mode to obscuro if non is set. """
        super().__init__(descriptor, outsubdir, runner)
        self.env = 'obscuro' if self.mode is None else self.mode

    def is_obscuro(self):
        """Return true if we are running against an Obscuro network. """
        return self.env in ['obscuro', 'obscuro.dev', 'obscuro.local']

    def fund_obx(self, network, web3_user, account_user, amount):
        """Fund OBX in the L2 to a users account, either through the faucet server or direct from the account."""
        if self.env in ['obscuro', 'obscuro.dev']:
            self.__obx_from_faucet_server(web3_user, account_user)
        else:
            self.__obx_from_funded_pk(network, web3_user, account_user, amount)

    def fund_obx_for_address_only(self, address):
        """Fund OBX for an account using the faucet server when only the address is known. """
        self.log.info('Increasing native OBX via the faucet server')
        headers = {'Content-Type': 'application/json'}
        data = {"address": address}
        requests.post(Properties().faucet_url(self.env), data=json.dumps(data), headers=headers)

    def transfer_token(self, network, token_name, token_address, web3_from, account_from, address, amount):
        """Transfer an ERC20 token amount from a recipient account to an address. """
        self.log.info('Running for token %s' % token_name)

        with open(os.path.join(PROJECT.root, 'src', 'solidity', 'erc20', 'erc20.json')) as f:
            token = web3_from.eth.contract(address=token_address, abi=json.load(f))

        balance = token.functions.balanceOf(account_from.address).call()
        self.log.info('Sender token balance before = %d ' % balance)

        # transfer tokens from the funded account to the distro account
        network.transact(self, web3_from, token.functions.transfer(address, amount), account_from, 7200000)

        balance = token.functions.balanceOf(account_from.address).call()
        self.log.info('Sender token balance after = %d ' % balance)

    def print_token_balance(self, token_name, token_address, web3, account):
        """Print an ERC20 token balance of a recipient account. """
        with open(os.path.join(PROJECT.root, 'src', 'solidity', 'erc20', 'erc20.json')) as f:
            token = web3.eth.contract(address=token_address, abi=json.load(f))

        balance = token.functions.balanceOf(account.address).call()
        self.log.info('Token balance for %s = %d ' % (token_name, balance))

    def __obx_from_faucet_server(self, web3_user, account_user):
        """Allocates native OBX to a users account from the faucet server."""
        self.log.info('Running for native OBX token using faucet server')
        user_obx = web3_user.eth.get_balance(account_user.address)
        self.log.info('L2 balances before;')
        self.log.info('  OBX User balance   = %d ' % user_obx)

        self.log.info('Running request on %s' % Properties().faucet_url(self.env))
        self.log.info('Running for user address %s' % account_user.address)
        headers = {'Content-Type': 'application/json'}
        data = {"address": account_user.address}
        requests.post(Properties().faucet_url(self.env), data=json.dumps(data), headers=headers)

        user_obx = web3_user.eth.get_balance(account_user.address)
        self.log.info('L2 balances after;')
        self.log.info('  OBX User balance   = %d ' % user_obx)

    def __obx_from_funded_pk(self, network, web3_user, account_user, amount):
        """Allocates native OBX to a users account from the pre-funded account."""
        self.log.info('Running for native OBX token using faucet pk')

        web3_funded, account_funded = network.connect(self, Properties().l2_funded_account_pk(self.env))
        funded_obx = web3_funded.eth.get_balance(account_funded.address)
        user_obx = web3_user.eth.get_balance(account_user.address)
        self.log.info('L2 balances before;')
        self.log.info('  OBX Funded balance = %d ' % funded_obx)
        self.log.info('  OBX User balance   = %d ' % user_obx)

        if user_obx < amount:
            amount = amount - user_obx

            # transaction from the faucet to the deployment account
            tx = {
                'nonce': web3_funded.eth.get_transaction_count(account_funded.address),
                'to': account_user.address,
                'value': amount,
                'gas': 4 * 720000,
                'gasPrice': 21000
            }
            tx_sign = account_funded.sign_transaction(tx)
            tx_hash = network.send_transaction(self, web3_funded, tx_sign)
            network.wait_for_transaction(self, web3_funded, tx_hash)

            funded_obx = web3_funded.eth.get_balance(account_funded.address)
            user_obx = web3_user.eth.get_balance(account_user.address)
            self.log.info('L2 balances after;')
            self.log.info('  OBX Funded balance = %d ' % funded_obx)
            self.log.info('  OBX User balance   = %d ' % user_obx)

    def run_python(self, script, stdout, stderr, args=None, state=BACKGROUND, timeout=120):
        """Run a python process."""
        self.log.info('Running python script %s' % os.path.basename(script))
        arguments = [script]
        if args is not None: arguments.extend(args)

        environ = copy.deepcopy(os.environ)
        hprocess = self.startProcess(command=sys.executable, displayName='python', workingDir=self.output,
                                     arguments=arguments, environs=environ, stdout=stdout, stderr=stderr,
                                     state=state, timeout=timeout)
        return hprocess

    def run_javascript(self, script, stdout, stderr, args=None, state=BACKGROUND, timeout=120):
        """Run a javascript process."""
        self.log.info('Running javascript %s' % os.path.basename(script))
        arguments = [script]
        if args is not None: arguments.extend(args)

        environ = copy.deepcopy(os.environ)
        hprocess = self.startProcess(command=Processes.get_node_bin(), displayName='node', workingDir=self.output,
                                     arguments=arguments, environs=environ, stdout=stdout, stderr=stderr,
                                     state=state, timeout=timeout)
        return hprocess

    def run_ws_proxy(self, remote_url, filename):
        """Run the websocket proxy to log messages."""
        script = os.path.join(PROJECT.root, 'utils', 'proxy', 'ws_proxy.py')
        stdout = os.path.join(self.output, 'proxy.out')
        stderr = os.path.join(self.output, 'proxy.err')

        host = '127.0.0.1'
        port = self.getNextAvailableTCPPort()
        arguments = []
        arguments.extend(['--host', host])
        arguments.extend(['--port', '%d' % port])
        arguments.extend(['--remote_url', remote_url])
        arguments.extend(['--filename', filename])
        self.run_python(script, stdout, stderr, arguments)
        return 'ws://%s:%d' % (host, port)
