# Copyright 2019 Huawei Technologies Co., Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import sys
import numpy as np
import pytest

from mindspore import Tensor
from mindspore import context
from mindspore.train.serialization import load_checkpoint, load_param_into_net

from mindarmour.attacks.black.natural_evolutionary_strategy import NES
from mindarmour.attacks.black.black_model import BlackModel

from mindarmour.utils.logger import LogUtil
from lenet5_net import LeNet5

sys.path.append("..")
from data_processing import generate_mnist_dataset

context.set_context(mode=context.GRAPH_MODE)
context.set_context(device_target="Ascend")

LOGGER = LogUtil.get_instance()
TAG = 'HopSkipJumpAttack'


class ModelToBeAttacked(BlackModel):
    """model to be attack"""

    def __init__(self, network):
        super(ModelToBeAttacked, self).__init__()
        self._network = network

    def predict(self, inputs):
        """predict"""
        if len(inputs.shape) == 3:
            inputs = inputs[np.newaxis, :]
        result = self._network(Tensor(inputs.astype(np.float32)))
        return result.asnumpy()


def random_target_labels(true_labels, labels_list):
    target_labels = []
    for label in true_labels:
        while True:
            target_label = np.random.choice(labels_list)
            if target_label != label:
                target_labels.append(target_label)
                break
    return target_labels


def _pseudorandom_target(index, total_indices, true_class):
    """ pseudo random_target """
    rng = np.random.RandomState(index)
    target = true_class
    while target == true_class:
        target = rng.randint(0, total_indices)
    return target


def create_target_images(dataset, data_labels, target_labels):
    res = []
    for label in target_labels:
        for i in range(len(data_labels)):
            if data_labels[i] == label:
                res.append(dataset[i])
                break
    return np.array(res)


@pytest.mark.level1
@pytest.mark.platform_arm_ascend_training
@pytest.mark.platform_x86_ascend_training
@pytest.mark.env_card
@pytest.mark.component_mindarmour
def test_nes_mnist_attack():
    """
    hsja-Attack test
    """
    # upload trained network
    ckpt_name = './trained_ckpt_file/checkpoint_lenet-10_1875.ckpt'
    net = LeNet5()
    load_dict = load_checkpoint(ckpt_name)
    load_param_into_net(net, load_dict)
    net.set_train(False)

    # get test data
    data_list = "./MNIST_unzip/test"
    batch_size = 32
    ds = generate_mnist_dataset(data_list, batch_size=batch_size)

    # prediction accuracy before attack
    model = ModelToBeAttacked(net)
    # the number of batches of attacking samples
    batch_num = 5
    test_images = []
    test_labels = []
    predict_labels = []
    i = 0
    for data in ds.create_tuple_iterator():
        i += 1
        images = data[0].astype(np.float32)
        labels = data[1]
        test_images.append(images)
        test_labels.append(labels)
        pred_labels = np.argmax(model.predict(images), axis=1)
        predict_labels.append(pred_labels)
        if i >= batch_num:
            break
    predict_labels = np.concatenate(predict_labels)
    true_labels = np.concatenate(test_labels)

    accuracy = np.mean(np.equal(predict_labels, true_labels))
    LOGGER.info(TAG, "prediction accuracy before attacking is : %s",
                accuracy)
    test_images = np.concatenate(test_images)

    # attacking
    scene = 'Query_Limit'
    if scene == 'Query_Limit':
        top_k = -1
    elif scene == 'Partial_Info':
        top_k = 5
    elif scene == 'Label_Only':
        top_k = 5

    success = 0
    queries_num = 0

    nes_instance = NES(model, scene, top_k=top_k)
    test_length = 32
    advs = []
    for img_index in range(test_length):
        # Initial image and class selection
        initial_img = test_images[img_index]
        orig_class = true_labels[img_index]
        initial_img = [initial_img]
        target_class = random_target_labels([orig_class], true_labels)
        target_image = create_target_images(test_images, true_labels,
                                            target_class)
        nes_instance.set_target_images(target_image)
        tag, adv, queries = nes_instance.generate(initial_img, target_class)
        if tag[0]:
            success += 1
        queries_num += queries[0]
        advs.append(adv)

    advs = np.reshape(advs, (len(advs), 1, 32, 32))
    adv_pred = np.argmax(model.predict(advs), axis=1)
    adv_accuracy = np.mean(np.equal(adv_pred, true_labels[:test_length]))
    LOGGER.info(TAG, "prediction accuracy after attacking is : %s",
                adv_accuracy)


if __name__ == '__main__':
    test_nes_mnist_attack()
