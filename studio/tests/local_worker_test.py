import unittest
import os
import shutil
import tempfile
import uuid
import subprocess
import time

from studio import model
from studio.local_queue import LocalQueue

from timeout_decorator import timeout
import logging

logging.basicConfig()


class LocalWorkerTest(unittest.TestCase):

    def test_runner_local(self):
        stubtest_worker(
            self,
            experiment_name='test_runner_local',
            runner_args=[],
            config_name='test_config.yaml',
            test_script='tf_hello_world.py',
            script_args=['arg0'],
            expected_output='[ 2.  6.]'
        )

    def test_local_worker_ce(self):

        tmpfile = os.path.join(tempfile.gettempdir(),
                               'tmpfile.txt')

        random_str1 = str(uuid.uuid4())
        with open(tmpfile, 'w') as f:
            f.write(random_str1)

        random_str2 = str(uuid.uuid4())
        experiment_name = 'test_local_worker_c' + str(uuid.uuid4())

        stubtest_worker(
            self,
            experiment_name=experiment_name,
            runner_args=['--capture=' + tmpfile + ':f'],
            config_name='test_config.yaml',
            test_script='art_hello_world.py',
            script_args=[random_str2],
            expected_output=random_str1
        )

        db = model.get_db_provider(model.get_config('test_config.yaml'))
        tmppath = os.path.join(tempfile.gettempdir(), str(uuid.uuid4()))

        db.store.get_artifact(
            db.get_experiment(experiment_name).artifacts['f'],
            tmppath)

        with open(tmppath, 'r') as f:
            self.assertTrue(f.read() == random_str2)
        os.remove(tmppath)

        stubtest_worker(
            self,
            experiment_name='test_local_worker_e',
            runner_args=['--reuse={}/f:f'.format(experiment_name)],
            config_name='test_config.yaml',
            test_script='art_hello_world.py',
            script_args=[],
            expected_output=random_str2
        )

    def test_local_worker_co(self):

        tmpfile = os.path.join(tempfile.gettempdir(),
                               'tmpfile.txt')

        random_str = str(uuid.uuid4())
        with open(tmpfile, 'w') as f:
            f.write(random_str)

        stubtest_worker(
            self,
            experiment_name='test_local_worker_co',
            runner_args=['--capture-once=' + tmpfile + ':f'],
            config_name='test_config.yaml',
            test_script='art_hello_world.py',
            script_args=[],
            expected_output=random_str
        )

    @timeout(60)
    def test_stop_experiment(self):
        my_path = os.path.dirname(os.path.realpath(__file__))
        os.chdir(my_path)

        logger = logging.getLogger('test_stop_experiment')
        logger.setLevel(10)

        config_name = 'test_config.yaml'
        key = 'test_stop_experiment'

        db = model.get_db_provider(model.get_config(config_name))
        try:
            db.delete_experiment(key)
        except Exception:
            pass

        p = subprocess.Popen(['studio-runner',
                              '--config=' + config_name,
                              '--experiment=' + key,
                              'stop_experiment.py'])

        # give experiment time to spin up
        time.sleep(20)
        logger.info('Stopping experiment')
        db.stop_experiment(key)
        p.wait()


def stubtest_worker(
        testclass,
        experiment_name,
        runner_args,
        config_name,
        test_script,
        script_args,
        expected_output,
        queue=LocalQueue(),
        wait_for_experiment=True,
        delete_when_done=True):

    my_path = os.path.dirname(os.path.realpath(__file__))
    os.chdir(my_path)

    queue.clean()

    db = model.get_db_provider(model.get_config(config_name))
    try:
        db.delete_experiment(experiment_name)
    except Exception:
        pass

    p = subprocess.Popen(['studio-runner'] + runner_args +
                         ['--config=' + config_name,
                          '--experiment=' + experiment_name,
                          test_script] + script_args,
                         stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT)

    pout, _ = p.communicate()

    try:
        # test saved arguments
        keybase = "/experiments/" + experiment_name
        saved_args = db[keybase + '/args']
        if saved_args is not None:
            testclass.assertTrue(len(saved_args) == len(script_args))
            for i in range(len(saved_args)):
                testclass.assertTrue(saved_args[i] == script_args[i])
            testclass.assertTrue(db[keybase + '/filename'] == test_script)
        else:
            testclass.assertTrue(script_args is None or len(script_args) == 0)

        experiment = db.get_experiment(experiment_name)
        if wait_for_experiment:
            while not experiment.status == 'finished':
                time.sleep(1)
                experiment = db.get_experiment(experiment_name)

        with open(db.store.get_artifact(experiment.artifacts['output']), 'r') \
                as f:
            data = f.read()
            split_data = data.strip().split('\n')
            testclass.assertEquals(split_data[-1], expected_output)

        check_workspace(testclass, db, experiment_name)

        if delete_when_done:
            db.delete_experiment(experiment_name)

    except Exception as e:
        print("Exception {} raised during test".format(e))
        print("worker output: \n {}".format(pout))
        raise e


def check_workspace(testclass, db, key):

    tmpdir = os.path.join(tempfile.gettempdir(), str(uuid.uuid4()))
    os.mkdir(tmpdir)
    db.store.get_artifact(db.get_experiment(key).artifacts['workspace'],
                          tmpdir, only_newer=False)

    for _, _, files in os.walk('.', topdown=False):
        for filename in files:
            downloaded_filename = os.path.join(tmpdir, filename)
            with open(downloaded_filename, 'rb') as f1:
                data1 = f1.read()
            with open(filename, 'rb') as f2:
                data2 = f2.read()

            testclass.assertTrue(
                data1 == data2,
                ('File comparison between local {} ' +
                 'and downloaded {} has failed')
                .format(
                    filename,
                    downloaded_filename))

    for _, _, files in os.walk('tmpdir', topdown=False):
        for filename in files:
            downloaded_filename = os.path.join(tmpdir, filename)
            with open(downloaded_filename, 'rb') as f1:
                data1 = f1.read()
            with open(filename, 'rb') as f2:
                data2 = f2.read()

            testclass.assertTrue(data1 == data2)

    shutil.rmtree(tmpdir)


if __name__ == "__main__":
    unittest.main()
