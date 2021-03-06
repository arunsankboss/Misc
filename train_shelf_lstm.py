#!/usr/bin/env python
import json
import cv2
import tensorflow.contrib.slim as slim
import datetime
import random
import time
import string
import argparse
import os
import threading
from scipy import misc
import tensorflow as tf
import numpy as np
from distutils.version import LooseVersion
if LooseVersion(tf.__version__) >= LooseVersion('1.0'):
    rnn_cell = tf.contrib.rnn
else:
    try:
        from tensorflow.models.rnn import rnn_cell
    except ImportError:
        rnn_cell = tf.nn.rnn_cell
from tensorflow.python.framework import ops
from tensorflow.python.ops import array_ops
#from tensorflow.contrib.keras.layers import ConvLSTM2D
from ConvRNN import ConvLSTMCell
random.seed(0)
np.random.seed(0)

from utils import train_utils, googlenet_load, tf_concat
import sys
sys.path.append("/usr/local/lib/python2.7/dist-packages/tensorflow/contrib/slim")
'''
@ops.RegisterGradient("Hungarian")
def _hungarian_grad(op, *args):
    return map(array_ops.zeros_like, op.inputs)
'''
"""
def build_lstm_inner(H, lstm_input):
    '''
    build lstm decoder
    '''
    lstm_cell = rnn_cell.BasicLSTMCell(H['lstm_size'], forget_bias=0.0, state_is_tuple=True)
    #h = H['lstm_size']
    print H['lstm_size']
    #lstm_cell = rnn_cell.LayerNormBasicLSTMCell(h, forget_bias=0.0, dropout_keep_prob=0.5)
    if H['num_lstm_layers'] > 1:
        lstm = rnn_cell.MultiRNNCell([lstm_cell] * H['num_lstm_layers'], state_is_tuple=True)
    else:
        lstm = lstm_cell

    batch_size = H['batch_size'] * H['grid_height'] * H['grid_width']
    print "Batch_size" , batch_size
    state = lstm.zero_state(batch_size, tf.float32)
    

    outputs = []
    print lstm
    with tf.variable_scope('RNN', initializer=tf.random_uniform_initializer(-0.1, 0.1)):
        for time_step in range(H['rnn_len']):
            if time_step > 0: tf.get_variable_scope().reuse_variables()
	    print "lstm shape", lstm_input.shape
	    print state
            output, state = lstm(lstm_input, state)
            outputs.append(output)
    return outputs
"""


def build_lstm_inner(H, lstm_input):
    '''
    build lstm decoder
    '''

    def get_lstm_cell(H):
        return rnn_cell.BasicLSTMCell(H['lstm_size'], forget_bias=0.0, state_is_tuple=True, reuse=tf.get_variable_scope().reuse)

    if H['num_lstm_layers'] > 1:
        lstm = rnn_cell.MultiRNNCell([get_lstm_cell(H) for _ in range(H['num_lstm_layers'])], state_is_tuple=True)
    else:
        lstm = get_lstm_cell(H)

    batch_size = H['batch_size'] * H['grid_height'] * H['grid_width']
    state = lstm.zero_state(batch_size, tf.float32)

    outputs = []
    with tf.variable_scope('RNN', initializer=tf.random_uniform_initializer(-0.1, 0.1)):
        for time_step in range(H['rnn_len']):
            if time_step > 0: tf.get_variable_scope().reuse_variables()
            output, state = lstm(lstm_input, state)
            outputs.append(output)
    return outputs

def build_soft_attention_inner(H, cnn):
    h = H['lstm_size']
    D = H['later_feat_channels']
    L = H['grid_width']*H['grid_height']
    #u_t = (1.0/L)*cnn # batch_size, grid_width x grid_height, feature_depth

    #lstm_cell = rnn_cell.LayerNormBasicLSTMCell(h, forget_bias=0.0, dropout_keep_prob=0.5)
    encoder_lstm = rnn_cell.LayerNormBasicLSTMCell(h, forget_bias=0.0, dropout_keep_prob=0.5)
    #lstm = rnn_cell.MultiRNNCell([lstm_cell]*H['num_lstm_layers'], state_is_tuple=True)
    #print lstm._state_is_tuple
    #s_t = lstm.zero_state(H['batch_size'], tf.float32)
    #c_t = (1.0/L)*tf.reduce_sum(cnn, 0, keep_dims=True) # (1,D)
    outputs = []
    for k in range(H['rnn_len']):
        with tf.variable_scope('attention', reuse=(k!=0)):
            attn_map_t = cnn * (1./L)
            with tf.variable_scope('lstm_init'):
                w_init_h  = tf.get_variable('w_init_h', [D,h], initializer=tf.contrib.layers.xavier_initializer())
                b_init_h = tf.get_variable('b_init_h',[h], initializer=tf.constant_initializer())
                #init_h = tf.nn.tanh(tf.matmul(c_t, w_init_h ) + b_init_h)
                init_h = tf.nn.tanh(tf.matmul(attn_map_t, w_init_h) + b_init_h)
                

                w_init_c  = tf.get_variable('w_init_c', [D,h], initializer=tf.contrib.layers.xavier_initializer())
                b_init_c = tf.get_variable('b_init_c',[h],  initializer=tf.constant_initializer())
                #init_c = tf.nn.tanh(tf.matmul(c_t, w_init_c) + b_init_c)
                init_c = tf.nn.tanh(tf.matmul(attn_map_t, w_init_c) + b_init_c )
            s_t =  rnn_cell.LSTMStateTuple(init_c, init_h)
            #print c_t.get_shape()
            
            for t in range(H['attn_len']+1):
                with tf.variable_scope('attention_lstm', reuse=(t!=0) ):
                    #if t==0:                
                    output,s_t = encoder_lstm(attn_map_t, s_t)
                    #print z_t.get_shape()
                    cell_state_t, z_t = s_t
                    #print z_t.shape
                    if t == H['attn_len']:
                        break    
                    w = tf.get_variable('w', [h, 1], dtype=tf.float32, initializer=tf.contrib.layers.xavier_initializer())
                    b = tf.get_variable('b', [L], initializer=tf.constant_initializer(0.0,tf.float32))
                    #w_att = tf.get_variable('w_att', [D, L], initializer=tf.contrib.layers.xavier_initializer())

                    h_att = tf.nn.tanh(tf.reshape(tf.matmul(z_t, w), [-1] ) + b)    #(L,h) * (h,L) --> (1,L)
                    #print h_att.shape
                    #out_att = tf.reshape(h_att, w_att))   
                    alpha_t = tf.nn.softmax(h_att) 

                    attn_map_t = cnn* tf.expand_dims(alpha_t, 1)
                    #print attn_map_t.shape
                    #c_t = tf.matmul(alpha_t,cnn) # (1,L) * (1*L,D) = (1 ,D)
                    #c_t = tf.reduce_sum(attn_map_t, 0, keep_dims=True)


            outputs.append(output)
    return outputs

def build_conv_attention_rnn(cnn, num_rnn_filters, attn_steps=3):
    #context_map = tf.ones(cnn.shape)*(1/(cnn.shape[1]*cnn.shape[2]))
    batch_size, h, w, channels = cnn.get_shape().as_list()
    L = h*w
    with tf.variable_scope('RNN', initializer=tf.contrib.layers.xavier_initializer_conv2d() ):
        cnn_map = tf.layers.conv2d(cnn, filters=num_rnn_filters, kernel_size=(1,1), name='attention_in_conv')
        
        with tf.variable_scope('Attention' ):
            conv_rnn = ConvLSTMCell([h,w], filters=num_rnn_filters, kernel=[3,3], peephole=False)
            for j in range(attn_steps):
                if j>0: 
                    tf.get_variable_scope().reuse_variables()
                    cnn_attn_map = cnn_map * context_map
                else:
                    cnn_attn_map = cnn_map * ( 1./ L)
                    
                    c = tf.layers.conv2d(inputs=cnn_attn_map, filters=num_rnn_filters, kernel_size=(1,1), activation=tf.nn.tanh, name='init_conv_c' )
                    h = tf.layers.conv2d(inputs=cnn_attn_map, filters=num_rnn_filters, kernel_size=(1,1), activation=tf.nn.tanh, name='init_conv_h' )
                    state = tf.contrib.rnn.LSTMStateTuple(c, h)
                    
    
                #ctx_map = tf.expand_dims(cnn_map, 0)
                
                conv_out, state = conv_rnn( cnn_attn_map,  state) #,  time_major=True )
                #conv_out = tf.reshape(conv_out,[-1, batch_size, h, w,num_rnn_filters ])
                #context = tf.layers.conv2d(conv_out, filters=num_rnn_filters, kernel_size=(1,1) , name='conv_context')
                context_map = tf.nn.softmax(conv_out)
        print conv_out.get_shape()
        #conv_final = tf.layers.conv2d(conv_out, filters=num_rnn_filters, kernel_size=(1,1), name='attention_out_conv')

    return conv_out
def build_conv_residual_attention_rnn(cnn, num_rnn_filters, attn_steps=3):
    #context_map = tf.ones(cnn.shape)*(1/(cnn.shape[1]*cnn.shape[2]))
    batch_size, h, w, channels = cnn.get_shape().as_list()
    L = h*w
    with tf.variable_scope('RNN' ):
        cnn_map = tf.layers.conv2d(cnn, filters=num_rnn_filters, kernel_size=(1,1), name='attention_in_conv')
        
        with tf.variable_scope('Attention' ):
            conv_rnn = ConvLSTMCell([h,w], filters=num_rnn_filters, kernel=[3,3], peephole=False)
            for j in range(attn_steps):
                if j>0: 
                    tf.get_variable_scope().reuse_variables()
                    cnn_attn_map = cnn_attn_map * (1.0 + context_map)
                else:
                    cnn_attn_map = cnn_map * ( 1./ L)
                    
                    c = tf.layers.conv2d(inputs=cnn_attn_map, filters=num_rnn_filters, kernel_size=(1,1), activation=tf.nn.tanh, name='init_conv_c' )
                    h = tf.layers.conv2d(inputs=cnn_attn_map, filters=num_rnn_filters, kernel_size=(1,1), activation=tf.nn.tanh, name='init_conv_h' )
                    state = tf.contrib.rnn.LSTMStateTuple(c, h)
                    
    
                #ctx_map = tf.expand_dims(cnn_map, 0)
                
                conv_out, state = conv_rnn( cnn_attn_map,  state) #,  time_major=True )
                #conv_out = tf.reshape(conv_out,[-1, batch_size, h, w,num_rnn_filters ])
                #context = tf.layers.conv2d(conv_out, filters=num_rnn_filters, kernel_size=(1,1) , name='conv_context')
                context_map = tf.nn.softmax(conv_out)
        print conv_out.get_shape()
        #conv_final = tf.layers.conv2d(conv_out, filters=num_rnn_filters, kernel_size=(1,1), name='attention_out_conv')

    return cnn_attn_map
        
def multiscale_attention(H, cnn_list, target_size, reuse=None):
    cnn_upsampled = []
    with tf.variable_scope('deconv', reuse=reuse):
        for j in range(cnn_list):
            upsample_weights_t = tf.get_variable(name="up_filter_%d"%j, initializer=tf.contrib.layers.xavier_initializer(), shape=[2*j+1, 2*j+1, cnn_list[j].shape[-1], 128 ])
            cnn_t = tf.nn.conv2d_transpose(cnn_list[j], upsample_weights_t, output_shape=[H['batch_size'], target_size[0], target_size[1], 128 ], strides=[1,2**j, 2**j, 1], name='deconv_%d'%j, padding='VALID' )
            cnn_upsampled.append(cnn_t)
        cnn_final = tf_concat(1, cnn_upsampled)
    w_merge = tf.get_variable('w_merge', shape=[3,3,128*len(cnn_list),256], initializer=tf.contrib.layers.xavier_initializer())
    cnn_merged = tf.nn.conv2d(cnn_final, w_merge, [1,2,2,1] )
    return cnn_merged

def sharp_mask_attention(H, cnn_list, target_size ):
    pass


def build_lstm_bidirectional_inner(H, lstm_input, lstm_rev_input):
    '''
    build bidirectional lstm decoder
    '''
    batch_size = H['batch_size'] * H['grid_height'] * H['grid_width']
    outputs = []
    with tf.variable_scope("bidirectional_rnn", initializer=tf.random_uniform_initializer(-0.1, 0.1)):
        with tf.variable_scope("fw"):
            lstm_fw_cell = rnn_cell.BasicLSTMCell(H['lstm_size']/2, forget_bias=0.0, state_is_tuple=False)
            if H['num_lstm_layers'] > 1:
                with tf.variable_scope("fw_lstm"):
                    lstm_fw = rnn_cell.MultiRNNCell([lstm_fw_cell] * H['num_lstm_layers'], state_is_tuple=False)
            else:
                lstm_fw = lstm_fw_cell
            with tf.variable_scope('fw_states'):
                state_fw = tf.zeros([batch_size, lstm_fw.state_size])
        with tf.variable_scope("bw"):
            lstm_bw_cell = rnn_cell.BasicLSTMCell(H['lstm_size']/2, forget_bias=0.0, state_is_tuple=False)
            if H['num_lstm_layers'] > 1:
                with tf.variable_scope("bw_lstm"):
                    lstm_bw = rnn_cell.MultiRNNCell([lstm_bw_cell] * H['num_lstm_layers'], state_is_tuple=False)
            else:
                lstm_bw = lstm_bw_cell
            with tf.variable_scope('bw_states'):
                state_bw = tf.zeros([batch_size, lstm_fw.state_size])
        for time_step in range(H['rnn_len']):
            if time_step > 0: tf.get_variable_scope().reuse_variables()
            with tf.variable_scope("fw"):
                output_fw, state_fw = lstm_fw(lstm_input, state_fw)
            with tf.variable_scope("bw"):
                output_bw, state_bw = lstm_bw(lstm_rev_input, state_bw)
            output = tf_concat(1, (output_fw, output_bw) )
            outputs.append(output)
    return outputs
def build_overfeat_inner(H, lstm_input):
    '''
    build simple overfeat decoder
    '''
    if H['rnn_len'] > 1:
        raise ValueError('rnn_len > 1 only supported with use_lstm == True')
    outputs = []
    
    initializer = tf.random_uniform_initializer(-0.1, 0.1)
    with tf.variable_scope('Overfeat', initializer=initializer):
        w = tf.get_variable('ip', shape=[H['later_feat_channels'], H['lstm_size']])
        outputs.append(tf.matmul(lstm_input, w))
    '''
    with tf.variable_scope('Overfeat'):
        encoder = tf.layers.conv2d(lstm_input, H['lstm_size'], 3,1, padding='same', name='encoder_conv')
        outputs.append(tf.reshape(encoder, [-1, H['lstm_size']]))
    '''

    return outputs

def deconv(x, output_shape, channels):
    k_h = 2
    k_w = 2
    w = tf.get_variable('w_deconv', initializer=tf.random_normal_initializer(stddev=0.01),
                        shape=[k_h, k_w, channels[1], channels[0]])
    y = tf.nn.conv2d_transpose(x, w, output_shape, strides=[1, k_h, k_w, 1], padding='VALID')
    return y

def rezoom(H, pred_boxes, early_feat, early_feat_channels, w_offsets, h_offsets):
    '''
    Rezoom into a feature map at multiple interpolation points in a grid.

    If the predicted object center is at X, len(w_offsets) == 3, and len(h_offsets) == 5,
    the rezoom grid will look as follows:

    [o o o]
    [o o o]
    [o X o]
    [o o o]
    [o o o]

    Where each letter indexes into the feature map with bilinear interpolation
    '''


    grid_size = H['grid_width'] * H['grid_height']
    outer_size = grid_size * H['batch_size']
    indices = []
    for w_offset in w_offsets:
        for h_offset in h_offsets:
            indices.append(train_utils.bilinear_select(H,
                                                       pred_boxes,
                                                       early_feat,
                                                       early_feat_channels,
                                                       w_offset, h_offset))

    interp_indices = tf_concat(0, indices)
    rezoom_features = train_utils.interp(early_feat,
                                         interp_indices,
                                         early_feat_channels)
    rezoom_features_r = tf.reshape(rezoom_features,
                                   [len(w_offsets) * len(h_offsets),
                                    outer_size,
                                    H['rnn_len'],
                                    early_feat_channels])
    rezoom_features_t = tf.transpose(rezoom_features_r, [1, 2, 0, 3])
    return tf.reshape(rezoom_features_t,
                      [outer_size,
                       H['rnn_len'],
                       len(w_offsets) * len(h_offsets) * early_feat_channels])

def build_forward(H, x, phase, reuse):
    '''
    Construct the forward model
    '''

    grid_size = H['grid_width'] * H['grid_height']
    outer_size = grid_size * H['batch_size']

    input_mean = 117.
    x -= input_mean
    cnn, early_feat = googlenet_load.model(x, H, reuse)
    #print cnn.get_shape()
    early_feat_channels = H['early_feat_channels']
    early_feat = early_feat[:, :, :, :early_feat_channels]
    up_ratio = int(round(np.log2(early_feat.get_shape().as_list() [1] / cnn.get_shape().as_list() [1])))

    if H['deconv']:
        with tf.variable_scope('Upsample',reuse=reuse):
            up = cnn
            for k in range(up_ratio):
                up = tf.layers.conv2d_transpose(up, early_feat_channels, 3, 2, padding='same',activation=tf.nn.elu, name='upsample_%d'%k  )
            #up2 = tf.layers.conv2d_transpose(up1, early_feat_channels, 3, 2, activation=tf.nn.relu, name='upsample')
            early_feat = tf.add(early_feat, up, name='merge_upsampled')



    elif H['avg_pool_size'] > 1:
        pool_size = H['avg_pool_size']
        cnn1 = cnn[:, :, :, :700]
        cnn2 = cnn[:, :, :, 700:]
        cnn2 = tf.nn.avg_pool(cnn2, ksize=[1, pool_size, pool_size, 1],
                              strides=[1, 1, 1, 1], padding='SAME')
        cnn = tf_concat(3, [cnn1, cnn2])

    if 'bidirectional' in H and H['bidirectional']:
        #print cnn.get_shape()
        vert_cnn = tf.transpose(cnn, perm=[0,2,1,3])
        #print cnn.get_shape()
        #reverse_cnn = tf.reverse(cnn, [2])
        #reverse_cnn = tf.reshape(reverse_cnn, H['batch_size'] * H['grid_width'] * H['grid_height'], H['later_feat_channels'])
    if phase == 'train':
    	cnn = tf.nn.dropout(cnn, 0.5)    
    initializer = tf.random_uniform_initializer(-0.1, 0.1)
    with tf.variable_scope('decoder', reuse=reuse,initializer=initializer):
        scale_down = 0.01
        if 'attention' in H :
            if H['attention'] == 'soft':
                cnn = tf.reshape(cnn,[H['batch_size'] * H['grid_width'] * H['grid_height'], H['later_feat_channels']])
                lstm_outputs = build_soft_attention_inner(H, cnn)
            elif H['attention'] == 'conv':
                lstm_outputs = build_conv_attention_rnn(cnn, H['lstm_size'], H['attn_size'])
                lstm_outputs = tf.reshape(lstm_outputs,[ H['rnn_len'],H['batch_size']*H['grid_width']*H['grid_height'], H['lstm_size']])
            elif H['attention'] == 'residual':
                lstm_outputs = build_conv_residual_attention_rnn(cnn, H['lstm_size'], H['attn_size'])  
                lstm_outputs = tf.reshape(lstm_outputs,[ H['rnn_len'],H['batch_size']*H['grid_width']*H['grid_height'], H['lstm_size']])  
            

        else:
            if 'bidirectional' in H and H['bidirectional']:
                lstm_input = tf.reshape(cnn * scale_down , (H['batch_size']*grid_size, H['later_feat_channels']))
                lstm_rev_input = tf.reshape(vert_cnn * scale_down, (H['batch_size']*grid_size, H['later_feat_channels']))
                lstm_outputs = build_lstm_bidirectional_inner(H, lstm_input, lstm_rev_input)
            else:
		lstm_input = tf.reshape(cnn * scale_down, (H['batch_size'] * grid_size, H['later_feat_channels']))
                if H['use_lstm']:
                    lstm_input = tf.reshape(cnn * scale_down, (H['batch_size'] * grid_size, H['later_feat_channels']))
                
                    lstm_outputs = build_lstm_inner(H, lstm_input)
                else:
                    lstm_outputs = build_overfeat_inner(H, lstm_input)

        pred_boxes = []
        pred_logits = []
        for k in range(H['rnn_len']):
            output = lstm_outputs[k]
            if phase == 'train' :
                output = tf.nn.dropout(output, 0.5)
            box_weights = tf.get_variable('box_ip%d' % k,
                                          shape=(H['lstm_size'], 4))
            conf_weights = tf.get_variable('conf_ip%d' % k,
                                           shape=(H['lstm_size'], H['num_classes']))
            
            pred_boxes_step = tf.reshape(tf.matmul(output, box_weights) * 50,
                                             [outer_size, 1, 4])

                
            pred_logits.append(tf.reshape(tf.matmul(output, conf_weights),
                                             [outer_size, 1, H['num_classes']]))
            
            pred_boxes.append(pred_boxes_step)

        pred_boxes = tf_concat(1, pred_boxes)
        pred_logits = tf_concat(1, pred_logits)
        pred_logits_squash = tf.reshape(pred_logits,
                                        [outer_size * H['rnn_len'], H['num_classes']])
        pred_confidences_squash = tf.nn.softmax(pred_logits_squash)
        pred_confidences = tf.reshape(pred_confidences_squash,
                                      [outer_size, H['rnn_len'], H['num_classes']])

        if H['use_rezoom']:
            pred_confs_deltas = []
            pred_boxes_deltas = []
            w_offsets = H['rezoom_w_coords']
            h_offsets = H['rezoom_h_coords']
            num_offsets = len(w_offsets) * len(h_offsets)
            rezoom_features = rezoom(H, pred_boxes, early_feat, early_feat_channels, w_offsets, h_offsets)
            if phase == 'train':
                rezoom_features = tf.nn.dropout(rezoom_features, 0.5)
            for k in range(H['rnn_len']):
                delta_features = tf_concat(1, [lstm_outputs[k], rezoom_features[:, k, :] / 1000.])
                dim = 128
                delta_weights1 = tf.get_variable(
                                    'delta_ip1%d' % k,
                                    shape=[H['lstm_size'] + early_feat_channels * num_offsets, dim])
                # TODO: add dropout here ?
                ip1 = tf.nn.relu(tf.matmul(delta_features, delta_weights1))
                if phase == 'train':
                    ip1 = tf.nn.dropout(ip1, 0.5)
                delta_confs_weights = tf.get_variable(
                                    'delta_ip2%d' % k,
                                    shape=[dim, H['num_classes']])
                if H['reregress']:
                    delta_boxes_weights = tf.get_variable(
                                        'delta_ip_boxes%d' % k,
                                        shape=[dim, 4])
                    pred_boxes_deltas.append(tf.reshape(tf.matmul(ip1, delta_boxes_weights) * 5,
                                                        [outer_size, 1, 4]))
                scale = H.get('rezoom_conf_scale', 50)
                pred_confs_deltas.append(tf.reshape(tf.matmul(ip1, delta_confs_weights) * scale,
                                                    [outer_size, 1, H['num_classes']]))
            pred_confs_deltas = tf_concat(1, pred_confs_deltas)
            if H['reregress']:
                pred_boxes_deltas = tf_concat(1, pred_boxes_deltas)
            return pred_boxes, pred_logits, pred_confidences, pred_confs_deltas, pred_boxes_deltas

    return pred_boxes, pred_logits, pred_confidences

def build_forward_backward(H, x, phase, boxes, flags):
    '''
    Call build_forward() and then setup the loss functions
    '''

    grid_size = H['grid_width'] * H['grid_height']
    outer_size = grid_size * H['batch_size'] 

    reuse = {'train': None, 'test': True}[phase]
    if H['use_rezoom']:
        (pred_boxes, pred_logits,
         pred_confidences, pred_confs_deltas, pred_boxes_deltas) = build_forward(H, x, phase, reuse)
    else:
        pred_boxes, pred_logits, pred_confidences = build_forward(H, x, phase, reuse)
    with tf.variable_scope('decoder', reuse={'train': None, 'test': True}[phase]):
        outer_boxes = tf.reshape(boxes, [outer_size, H['rnn_len'], 4])
        outer_flags = tf.cast(tf.reshape(flags, [outer_size, H['rnn_len']]), 'int32')
        '''
        if H['use_lstm']:
            hungarian_module = tf.load_op_library('utils/hungarian/hungarian.so')
            assignments, classes, perm_truth, pred_mask = (
                hungarian_module.hungarian(pred_boxes, outer_boxes, outer_flags, H['solver']['hungarian_iou']))
        else:
        '''
        classes = tf.reshape(flags, (outer_size, 1))
        perm_truth = tf.reshape(outer_boxes, (outer_size, 1, 4))
        pred_mask = tf.reshape(tf.cast(tf.greater(classes, 0), 'float32'), (outer_size, 1, 1))
        true_classes = tf.reshape(tf.cast(tf.greater(classes, 0), 'int64'),
                                  [outer_size * H['rnn_len']])
        pred_logit_r = tf.reshape(pred_logits,
                                  [outer_size * H['rnn_len'], H['num_classes']])
        confidences_loss = (tf.reduce_sum(
            tf.nn.sparse_softmax_cross_entropy_with_logits(logits=pred_logit_r, labels=true_classes))
            ) / outer_size * H['solver']['head_weights'][0] * 0.5
        residual = tf.reshape(perm_truth - pred_boxes * pred_mask,
                              [outer_size, H['rnn_len'], 4])
        boxes_loss = tf.reduce_sum(tf.abs(residual)) / outer_size * H['solver']['head_weights'][1]
        if H['use_rezoom']:
            if H['rezoom_change_loss'] == 'center':
                error = (perm_truth[:, :, 0:2] - pred_boxes[:, :, 0:2]) / tf.maximum(perm_truth[:, :, 2:4], 1.)
                square_error = tf.reduce_sum(tf.square(error), 2)
                inside = tf.reshape(tf.to_int64(tf.logical_and(tf.less(square_error, 0.2**2), tf.greater(classes, 0))), [-1])
            elif H['rezoom_change_loss'] == 'iou':
                iou = train_utils.iou(train_utils.to_x1y1x2y2(tf.reshape(pred_boxes, [-1, 4])),
                                      train_utils.to_x1y1x2y2(tf.reshape(perm_truth, [-1, 4])))
                inside = tf.reshape(tf.to_int64(tf.greater(iou, 0.5)), [-1])
            else:
                assert H['rezoom_change_loss'] == False
                inside = tf.reshape(tf.to_int64((tf.greater(classes, 0))), [-1])
            new_confs = tf.reshape(pred_confs_deltas, [outer_size * H['rnn_len'], H['num_classes']])
            delta_confs_loss = tf.reduce_sum(
                tf.nn.sparse_softmax_cross_entropy_with_logits(logits=new_confs, labels=inside)) / outer_size * H['solver']['head_weights'][0] * 0.5

            pred_logits_squash = tf.reshape(new_confs,
                                            [outer_size * H['rnn_len'], H['num_classes']])
            pred_confidences_squash = tf.nn.softmax(pred_logits_squash)
            pred_confidences = tf.reshape(pred_confidences_squash,
                                      [outer_size, H['rnn_len'], H['num_classes']])
            loss = confidences_loss + boxes_loss + delta_confs_loss
            if H['reregress']:
                delta_residual = tf.reshape(perm_truth - (pred_boxes + pred_boxes_deltas) * pred_mask,
                                            [outer_size, H['rnn_len'], 4])
                delta_boxes_loss = (tf.reduce_sum(tf.minimum(tf.square(delta_residual), 10. ** 2)) /
                               outer_size * H['solver']['head_weights'][1] * 0.03)
                boxes_loss = delta_boxes_loss

                tf.summary.histogram(phase + '/delta_hist0_x', pred_boxes_deltas[:, 0, 0])
                tf.summary.histogram(phase + '/delta_hist0_y', pred_boxes_deltas[:, 0, 1])
                tf.summary.histogram(phase + '/delta_hist0_w', pred_boxes_deltas[:, 0, 2])
                tf.summary.histogram(phase + '/delta_hist0_h', pred_boxes_deltas[:, 0, 3])
                loss += delta_boxes_loss
        else:
            loss = confidences_loss + boxes_loss

    return pred_boxes, pred_confidences, loss, confidences_loss, boxes_loss

def build(H, q):
    '''
    Build full model for training, including forward / backward passes,
    optimizers, and summary statistics.
    '''
    arch = H
    solver = H["solver"]

    os.environ['CUDA_VISIBLE_DEVICES'] = str(solver.get('gpu', ''))

    #gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=0.8)
    gpu_options = tf.GPUOptions(allow_growth=True)

    config = tf.ConfigProto(gpu_options=gpu_options, log_device_placement=True)

    learning_rate = tf.placeholder(tf.float32)
    if solver['opt'] == 'RMS':
        opt = tf.train.RMSPropOptimizer(learning_rate=learning_rate,
                                        decay=0.9, epsilon=solver['epsilon'])
    elif solver['opt'] == 'Adam':
        opt = tf.train.AdamOptimizer(learning_rate=learning_rate, epsilon=solver['epsilon'])
    elif solver['opt'] == 'SGD':
        opt = tf.train.GradientDescentOptimizer(learning_rate=learning_rate)
    else:
        raise ValueError('Unrecognized opt type')
    loss, recall, precision, confidences_loss, boxes_loss = {}, {}, {}, {}, {}
    for phase in ['train', 'test']:
        # generate predictions and losses from forward pass
        x, confidences, boxes = q[phase].dequeue_many(arch['batch_size'])
        flags = tf.argmax(confidences, 3)


        grid_size = H['grid_width'] * H['grid_height']

        (pred_boxes, pred_confidences,
         loss[phase], confidences_loss[phase],
         boxes_loss[phase]) = build_forward_backward(H, x, phase, boxes, flags)
        pred_confidences_r = tf.reshape(pred_confidences, [H['batch_size'], grid_size, H['rnn_len'], arch['num_classes']])
        pred_boxes_r = tf.reshape(pred_boxes, [H['batch_size'], grid_size, H['rnn_len'], 4])


        # Set up summary operations for tensorboard
        #a = tf.equal(tf.argmax(confidences[:, :, 0, :], 2), tf.argmax(pred_confidences_r[:, :, 0, :], 2))
        #accuracy[phase] = tf.reduce_mean(tf.cast(a, 'float32'), name=phase+'/accuracy')
        grid_gt = tf.argmax(confidences[:,:,0,:], 2)
        grid_pred = tf.argmax(pred_confidences_r[:,:,0,:], 2)
        _,precision[phase] = tf.metrics.precision(grid_gt, grid_pred  )
        _,recall[phase]= tf.metrics.recall(grid_gt, grid_pred )
        if phase == 'train':
            global_step = tf.Variable(0, trainable=False)

            tvars = tf.trainable_variables()
            if 'start_train_layer' in H:
                tvars = []
                start_flag = False
                for var in tf.trainable_variables():
                    if var.name.startswith(H['start_train_layer']):
                        start_flag = True

                    if start_flag:
                        tvars.append(var)
            for var in tvars:
                print var.name
            if H['clip_norm'] <= 0:
                grads = tf.gradients(loss['train'], tvars)
            else:
                grads, norm = tf.clip_by_global_norm(tf.gradients(loss['train'], tvars), H['clip_norm'])
            train_op = opt.apply_gradients(zip(grads, tvars), global_step=global_step)
        elif phase == 'test':
            '''
            moving_avg = tf.train.ExponentialMovingAverage(0.95)
            smooth_op = moving_avg.apply([accuracy['train'], accuracy['test'],
                                          confidences_loss['train'], boxes_loss['train'],
                                          confidences_loss['test'], boxes_loss['test'],
                                          ])
            '''

            for p in ['train', 'test']:
                tf.summary.scalar('%s/recall' % p, recall[p])
                tf.summary.scalar('%s/precision' % p, precision[p])
                tf.summary.scalar("%s/confidences_loss" % p, confidences_loss[p])
                #tf.summary.scalar("%s/confidences_loss/smooth" % p, moving_avg.average(confidences_loss[p]))
                tf.summary.scalar("%s/regression_loss" % p, boxes_loss[p])
                #tf.summary.scalar("%s/regression_loss/smooth" % p, moving_avg.average(boxes_loss[p]))
                tf.summary

        if phase == 'test':
            test_image = x
            # show ground truth to verify labels are correct
            test_true_confidences = confidences[0, :, :, :]
            test_true_boxes = boxes[0, :, :, :]

            # show predictions to visualize training progress
            test_pred_confidences = pred_confidences_r[0, :, :, :]
            test_pred_boxes = pred_boxes_r[0, :, :, :]

            def log_image(np_img, np_confidences, np_boxes, np_global_step, pred_or_true):

                merged = train_utils.add_rectangles(H, np_img, np_confidences, np_boxes,
                                                    use_stitching=True,
                                                    rnn_len=H['rnn_len'])[0]

                num_images = 1
                img_path = os.path.join(H['save_dir'], '%s_%s.jpg' % ((np_global_step / H['logging']['display_iter']) % num_images, pred_or_true))
                misc.imsave(img_path, merged)
                return merged

            pred_log_img = tf.py_func(log_image,
                                      [test_image, test_pred_confidences, test_pred_boxes, global_step, 'pred'],
                                      [tf.float32])
            true_log_img = tf.py_func(log_image,
                                      [test_image, test_true_confidences, test_true_boxes, global_step, 'true'],
                                      [tf.float32])
            tf.summary.image(phase + '/pred_boxes', pred_log_img, max_outputs=10)
            tf.summary.image(phase + '/true_boxes', true_log_img, max_outputs=10)

    summary_op = tf.summary.merge_all()

    return (config, loss, recall, precision, summary_op, train_op,
             global_step, learning_rate)


def train(H, test_images):
    '''
    Setup computation graph, run 2 prefetch data threads, and then run the main loop
    '''

    if not os.path.exists(H['save_dir']): os.makedirs(H['save_dir'])

    ckpt_file = H['save_dir'] + '/save.ckpt'
    with open(H['save_dir'] + '/hypes.json', 'w') as f:
        json.dump(H, f, indent=4)

    x_in = tf.placeholder(tf.float32)
    confs_in = tf.placeholder(tf.float32)
    boxes_in = tf.placeholder(tf.float32)
    q = {}
    enqueue_op = {}
    for phase in ['train', 'test']:
        dtypes = [tf.float32, tf.float32, tf.float32]
        grid_size = H['grid_width'] * H['grid_height']
        shapes = (
            [H['image_height'], H['image_width'], 3],
            [grid_size, H['rnn_len'], H['num_classes']],
            [grid_size, H['rnn_len'], 4],
            )
        q[phase] = tf.FIFOQueue(capacity=50, dtypes=dtypes, shapes=shapes)
        enqueue_op[phase] = q[phase].enqueue((x_in, confs_in, boxes_in))

    def make_feed(d):
        return {x_in: d['image'], confs_in: d['confs'], boxes_in: d['boxes'],
                learning_rate: H['solver']['learning_rate']}

    def thread_loop(sess, enqueue_op, phase, gen):
        for d in gen:
            sess.run(enqueue_op[phase], feed_dict=make_feed(d))

    (config, loss, recall, precision, summary_op, train_op,
      global_step, learning_rate) = build(H, q)

    saver = tf.train.Saver(max_to_keep=None)
    writer = tf.summary.FileWriter(
        logdir=H['save_dir'],
        flush_secs=10
    )

    with tf.Session(config=config) as sess:
        tf.train.start_queue_runners(sess=sess)
        for phase in ['train', 'test']:
            # enqueue once manually to avoid thread start delay
            gen = train_utils.load_data_gen(H, phase, jitter=H['solver']['use_jitter'])
            d = gen.next()
            sess.run(enqueue_op[phase], feed_dict=make_feed(d))
            t = threading.Thread(target=thread_loop,
                                 args=(sess, enqueue_op, phase, gen))
            t.daemon = True
            t.start()

        tf.set_random_seed(H['solver']['rnd_seed'])
        sess.run(tf.initialize_all_variables())
        sess.run(tf.local_variables_initializer())
        writer.add_graph(sess.graph)
        weights_str = H['solver']['weights']
        if len(weights_str) > 0:
            print('Restoring from: %s' % weights_str)
            saver.restore(sess, weights_str)
        else:
            init_fn = slim.assign_from_checkpoint_fn(
                  '%s/data/%s' % (os.path.dirname(os.path.realpath(__file__)), H['slim_ckpt']),
                  [x for x in tf.all_variables() if x.name.startswith(H['slim_basename']) and H['solver']['opt'] not in x.name])
            #init_fn = slim.assign_from_checkpoint_fn(
                  #'%s/data/inception_v1.ckpt' % os.path.dirname(os.path.realpath(__file__)),
                  #[x for x in tf.all_variables() if x.name.startswith('InceptionV1') and not H['solver']['opt'] in x.name])
            init_fn(sess)

        # train model for N iterations
        #for var in tf.trainable_variables():
        #    print var.name
        start = time.time()
        max_iter = H['solver']['max_iter']#.get('max_iter', 10000000)
        for i in xrange(max_iter):
            display_iter = H['logging']['display_iter']
            adjusted_lr = (H['solver']['learning_rate'] *
                           0.5 ** max(0, (i / H['solver']['learning_rate_step']) - 1))
            lr_feed = {learning_rate: adjusted_lr}

            if i % display_iter != 0:
                # train network
                batch_loss_train, _ = sess.run([loss['train'], train_op], feed_dict=lr_feed)
            else:
                # test network every N iterations; log additional info
                if i > 0:
                    dt = (time.time() - start) / (H['batch_size'] * display_iter)
                start = time.time()
                (train_loss, test_recall, test_precision, summary_str,
                    _) = sess.run([loss['train'], recall['test'],precision['test'],
                                      summary_op, train_op, 
                                     ], feed_dict=lr_feed)
                writer.add_summary(summary_str, global_step=global_step.eval())
                print_str = string.join([
                    'Step: %d',
                    'lr: %f',
                    'Train Loss: %.2f',
                    'Softmax Test Recall: %.1f%%',
                    'Softmax Test Precision: %.1f%%'
                    'Time/image (ms): %.1f'
                ], ', ')
                print(print_str %
                      (i, adjusted_lr, train_loss,
                       test_recall * 100, test_precision*100, dt * 1000 if i > 0 else 0))
	    if global_step.eval() == 60000:
		saver.save(sess, ckpt_file, global_step=10)
		

            if global_step.eval() % H['logging']['save_iter'] == 0 or global_step.eval() == max_iter - 1:
                saver.save(sess, ckpt_file, global_step=global_step)


def main():
    '''
    Parse command line arguments and return the hyperparameter dictionary H.
    H first loads the --hypes hypes.json file and is further updated with
    additional arguments as needed.
    '''
    parser = argparse.ArgumentParser()
    parser.add_argument('--weights', default=None, type=str)
    parser.add_argument('--gpu', default=None, type=int)
    parser.add_argument('--hypes', required=True, type=str)
    parser.add_argument('--logdir', default='output', type=str)
    args = parser.parse_args()
    with open(args.hypes, 'r') as f:
        H = json.load(f)
    if args.gpu is not None:
        H['solver']['gpu'] = args.gpu
    if len(H.get('exp_name', '')) == 0:
        H['exp_name'] = args.hypes.split('/')[-1].replace('.json', '')
    H['save_dir'] = args.logdir + '/%s_%s' % (H['exp_name'],
        datetime.datetime.now().strftime('%Y_%m_%d_%H.%M'))
    if args.weights is not None:
        H['solver']['weights'] = args.weights
    print H['image_height']
    train(H, test_images=[])

if __name__ == '__main__':
    main()
